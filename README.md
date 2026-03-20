# CineScope — Film Strategic Analytics

An AI-powered film pre-production analytics tool for film students and creators.

## Features
- Input your film's genre, tone, theme, budget, audience, and more
- Finds similar films via TMDB API
- Calculates a predicted commercial success rate
- AI-powered strategic suggestions and alternative routes via Google Gemini

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up your .env file
Create a `.env` file in the project root (copy from `.env.example`):
```
TMDB_API_KEY=your_tmdb_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

Get your keys:
- TMDB: https://www.themoviedb.org/settings/api
- Gemini: https://aistudio.google.com/app/apikey

### 3. Run the app
```bash
python app.py
```

Then open http://localhost:5000 in your browser.

## Project Structure
```
/
├── app.py              # Flask backend
├── templates/
│   └── index.html      # Frontend UI
├── requirements.txt
├── .env.example
└── README.md
```
