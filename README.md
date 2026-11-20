# TestPilot AI — LLM-Guided UI Test Case Generator

Turn product requirements and application context into structured UI test scenarios, then execute supported scenarios against a real browser with Playwright.

> Generated scenarios and executed results are separate. A test is only marked passed or failed after browser execution. Example-library entries are templates, not claimed execution results.

## Features
- Upload requirements and UI context files.
- Generate structured test cases with an OpenAI LLM.
- Review priorities, steps, selectors, and expected outcomes.
- Execute supported browser actions with Playwright.
- Inspect pass/fail results and execution screenshots.
- Review saved suites and export reports as JSON.
- Dashboard metrics are backed by the local API/database, not hard-coded demo counters.

## Stack
React + Vite · Python + FastAPI · OpenAI API · Playwright (Chromium) · SQLite

## Requirements
Python 3.10+, Node.js 18+, an OpenAI API key, and a target app reachable from the backend machine.

## Run locally (Windows PowerShell)

### Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
Add your key to `backend/.env`:
```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```
Install Chromium and start the API:
```powershell
playwright install chromium
uvicorn main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

### Frontend (new terminal)
```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```
Open http://localhost:5173.

## Configuration
Set `VITE_API_URL` in `frontend/.env` to the backend base URL (default `http://localhost:8000`). Keep API keys only in `backend/.env`; never expose secrets in frontend variables or commit `.env` files.

## Push to GitHub
Create an empty GitHub repository, then run from the project root:
```bash
git init
git add .
git commit -m "Build TestPilot AI UI test generator"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

## Deployment
The frontend and backend are separate services. Deploy FastAPI to a Python host that supports Playwright/Chromium and persistent storage. Configure CORS for your frontend domain, set `OPENAI_API_KEY` as a server-side secret, and set `VITE_API_URL` to the deployed backend base URL. GitHub Pages can host the static frontend build, but cannot run FastAPI or Playwright; deploy both services for the complete working application.

## Screenshots
Add genuine screenshots after running locally: `docs/screenshots/dashboard.png`, `docs/screenshots/generate-tests.png`, and `docs/screenshots/execution-results.png`. Do not add fabricated screenshots or placeholder execution results.

## Scope and limitations
This is a functional starter implementation. LLM generation requires a valid API key. Browser execution depends on generated action types/selectors being supported and the target application being reachable. Review generated steps before running against non-test environments.
