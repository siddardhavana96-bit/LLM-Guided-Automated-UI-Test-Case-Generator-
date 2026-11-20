import os, json, sqlite3, uuid, base64, mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from urllib.parse import urljoin
from pydantic import BaseModel, HttpUrl
from openai import OpenAI

ROOT = Path(__file__).parent
UPLOADS = ROOT / 'uploads'
UPLOADS.mkdir(exist_ok=True)
SCREENSHOTS = ROOT / 'screenshots'
SCREENSHOTS.mkdir(exist_ok=True)
app.mount('/screenshots', StaticFiles(directory=SCREENSHOTS), name='screenshots')
DB = ROOT / 'app.db'
app = FastAPI(title='LLM-Guided UI Test Case Generator', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

with db() as con:
    con.execute('''CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, title TEXT, source TEXT, target_url TEXT, cases TEXT, results TEXT, created_at TEXT)''')

class GenerateRequest(BaseModel):
    title: str = 'Untitled test suite'
    context: str = ''
    target_url: Optional[str] = None
    file_id: Optional[str] = None

class ExecuteRequest(BaseModel):
    run_id: str
    target_url: str

@app.get('/api/health')
def health():
    return {'status':'ok','llm_configured':bool(os.getenv('OPENAI_API_KEY'))}

@app.get('/api/dashboard')
def dashboard():
    with db() as con:
        rows = con.execute('SELECT cases, results FROM runs').fetchall()
    total = passed = failed = 0
    for r in rows:
        cases = json.loads(r['cases'] or '[]'); results = json.loads(r['results'] or '[]')
        total += len(cases)
        passed += sum(x.get('status') == 'passed' for x in results)
        failed += sum(x.get('status') == 'failed' for x in results)
    return {'suites':len(rows),'test_cases':total,'passed':passed,'failed':failed,'pending':max(total-passed-failed,0)}

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    allowed = {'.txt','.md','.pdf','.docx','.png','.jpg','.jpeg','.webp'}
    if ext not in allowed: raise HTTPException(400, 'Supported files: PDF, DOCX, TXT, MD, PNG, JPG, WEBP')
    data = await file.read()
    if len(data) > 12 * 1024 * 1024: raise HTTPException(413, 'Maximum upload size is 12 MB')
    fid = str(uuid.uuid4())
    path = UPLOADS / f'{fid}{ext}'; path.write_bytes(data)
    text = ''
    try:
        if ext in {'.txt','.md'}: text = data.decode('utf-8', errors='replace')
        elif ext == '.pdf':
            from pypdf import PdfReader
            import io
            text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages)
        elif ext == '.docx':
            from docx import Document
            import io
            text = '\n'.join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    except Exception as e: text = f'[Text extraction note: {e}]'
    return {'file_id':fid,'filename':file.filename,'text':text,'is_image':ext in {'.png','.jpg','.jpeg','.webp'},'message':'Upload received'}

@app.post('/api/generate')
def generate(req: GenerateRequest):
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503, 'LLM is not configured. Add OPENAI_API_KEY to backend/.env and restart the API.')
    context = req.context.strip()
    image_data = None
    if req.file_id:
        matches = list(UPLOADS.glob(req.file_id + '.*'))
        if not matches: raise HTTPException(404, 'Uploaded file not found')
        path = matches[0]
        if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
            mime = mimetypes.guess_type(path.name)[0] or 'image/png'
            image_data = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()
        else:
            ext = path.suffix.lower()
            if ext in {'.txt','.md'}: context += '\n' + path.read_text(errors='replace')
            elif ext == '.pdf':
                from pypdf import PdfReader
                context += '\n' + '\n'.join(p.extract_text() or '' for p in PdfReader(str(path)).pages)
            elif ext == '.docx':
                from docx import Document
                context += '\n' + '\n'.join(p.text for p in Document(str(path)).paragraphs)
    if not context and not image_data: raise HTTPException(400, 'Provide application context or upload a requirements file/screenshot.')
    client = OpenAI()
    prompt = '''You are a senior QA engineer. Turn the supplied application context into practical UI test cases. Return ONLY valid JSON with this schema: {"summary":"...","cases":[{"id":"TC-001","title":"...","category":"Functional|Validation|Navigation|Accessibility|Negative","priority":"High|Medium|Low","preconditions":["..."],"steps":[{"action":"navigate|click|fill|assert_text|assert_visible|wait","selector":"CSS selector or empty","value":"URL, text, or empty","description":"human-readable action"}],"expected_result":"..."}]}. Include 5-10 meaningful cases. Use robust CSS selectors where possible. If selectors cannot be inferred, say so in description and use a plausible semantic selector. Never claim tests were executed.'''
    content = [{'type':'input_text','text':prompt+'\nApplication title: '+req.title+'\nTarget URL: '+str(req.target_url or 'Not provided')+'\nContext:\n'+context}]
    if image_data: content.append({'type':'input_image','image_url':image_data})
    try:
        response = client.responses.create(model=os.getenv('OPENAI_MODEL','gpt-4.1-mini'), input=[{'role':'user','content':content}])
        raw = response.output_text
        data = json.loads(raw[raw.find('{'):raw.rfind('}')+1])
        cases = data.get('cases', [])
        if not cases: raise ValueError('No test cases returned')
    except Exception as e: raise HTTPException(502, f'LLM generation failed: {e}')
    rid = str(uuid.uuid4())
    with db() as con:
        con.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(rid,req.title,context[:2000],req.target_url,json.dumps(cases),json.dumps([]),datetime.utcnow().isoformat()))
    return {'run_id':rid,'summary':data.get('summary','Test cases generated.'),'cases':cases}

@app.post('/api/execute')
async def execute(req: ExecuteRequest):
    with db() as con:
        row = con.execute('SELECT cases FROM runs WHERE id=?',(req.run_id,)).fetchone()
    if not row: raise HTTPException(404,'Test suite not found')
    cases = json.loads(row['cases'])
    try:
        from playwright.async_api import async_playwright
    except ImportError: raise HTTPException(503,'Playwright is missing. Run: playwright install chromium')
    results=[]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for case in cases:
            page = await browser.new_page(); steps_out=[]; status='passed'; error=''
            try:
                for step in case.get('steps',[]):
                    action=step.get('action'); selector=step.get('selector') or ''; value=step.get('value') or ''
                    if action=='navigate': await page.goto(urljoin(req.target_url.rstrip('/')+'/', value or ''), wait_until='domcontentloaded', timeout=20000)
                    elif action=='click': await page.locator(selector).first.click(timeout=10000)
                    elif action=='fill': await page.locator(selector).first.fill(value, timeout=10000)
                    elif action=='assert_text':
                        if selector: await page.locator(selector).first.get_by_text(value).wait_for(timeout=8000)
                        else: await page.get_by_text(value).first.wait_for(timeout=8000)
                    elif action=='assert_visible': await page.locator(selector).first.wait_for(state='visible', timeout=8000)
                    elif action=='wait': await page.wait_for_timeout(min(int(value or 1000),5000))
                    else: steps_out.append({'step':step.get('description','Unknown action'),'status':'skipped'}); continue
                    steps_out.append({'step':step.get('description',action),'status':'passed'})
            except Exception as e:
                status='failed'; error=str(e)[:500]
                steps_out.append({'step':'Execution stopped','status':'failed','error':error})
            shot_name = f'{req.run_id}_{case.get("id", uuid.uuid4().hex)}.png'
            shot_path = SCREENSHOTS / shot_name
            try: await page.screenshot(path=str(shot_path), full_page=True)
            except Exception: shot_name = ''
            results.append({'case_id':case.get('id'),'title':case.get('title'),'status':status,'error':error,'steps':steps_out,'screenshot_url':f'/screenshots/{shot_name}' if shot_name else None})
            await page.close()
        await browser.close()
    with db() as con: con.execute('UPDATE runs SET results=?, target_url=? WHERE id=?',(json.dumps(results),req.target_url,req.run_id))
    return {'run_id':req.run_id,'results':results,'summary':{'total':len(results),'passed':sum(x['status']=='passed' for x in results),'failed':sum(x['status']=='failed' for x in results)}}

@app.get('/api/history')
def history():
    with db() as con: rows=con.execute('SELECT id,title,target_url,cases,results,created_at FROM runs ORDER BY created_at DESC').fetchall()
    return [{'id':r['id'],'title':r['title'],'target_url':r['target_url'],'case_count':len(json.loads(r['cases'])),'results':json.loads(r['results'] or '[]'),'created_at':r['created_at']} for r in rows]

@app.get('/api/examples')
def examples():
    return [
      {'id':'EX-001','title':'Login with valid credentials','category':'Authentication','priority':'High','expected_result':'User is authenticated and redirected to the dashboard.','steps':[{'action':'navigate','selector':'','value':'/login','description':'Open login page'},{'action':'fill','selector':'input[name="email"]','value':'qa@example.com','description':'Enter registered email'},{'action':'fill','selector':'input[name="password"]','value':'ValidPassword123!','description':'Enter valid password'},{'action':'click','selector':'button[type="submit"]','value':'','description':'Submit login form'},{'action':'assert_visible','selector':'[data-testid="dashboard"]','value':'','description':'Verify dashboard is visible'}]},
      {'id':'EX-002','title':'Reject invalid email format','category':'Validation','priority':'High','expected_result':'Inline validation is shown and the form is not submitted.','steps':[{'action':'navigate','selector':'','value':'/signup','description':'Open sign-up page'},{'action':'fill','selector':'input[name="email"]','value':'not-an-email','description':'Enter malformed email'},{'action':'click','selector':'button[type="submit"]','value':'','description':'Submit form'},{'action':'assert_visible','selector':'[role="alert"]','value':'','description':'Check validation message'}]},
      {'id':'EX-003','title':'Password reset navigation','category':'Navigation','priority':'Medium','expected_result':'Password reset form is displayed.','steps':[{'action':'navigate','selector':'','value':'/login','description':'Open login page'},{'action':'click','selector':'a[href*="forgot"]','value':'','description':'Select forgot password'},{'action':'assert_visible','selector':'input[type="email"]','value':'','description':'Verify reset form'}]}
    ]
