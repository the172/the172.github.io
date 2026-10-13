Wonchul Kim personal website

Main files:
- index.html
- assets/wonchul-kim-profile.jpg (original supplied profile photo; not retouched)
- assets/articles.js (article lists for the 4 tabs; auto-updated weekly)
- assets/Bio_Wonchul_Kim.docx
- scripts/update_articles.py (weekly updater)
- .github/workflows/update-articles.yml (runs the updater and deploys)

Article tabs (assets/articles.js):
- reportage : titles tagged [Reportage]
- interview : titles tagged [Interview]
- column    : titles tagged [Correspondent's column]
- latest    : newest 9 articles of any kind

Automatic update (every Monday, or Actions > Auto Update Articles > Run workflow):
1. Search Google News for Kim Won-chul articles on The Hankyoreh English Edition.
2. Open each new article and keep it only if the byline is Kim Won-chul.
3. Classify by the title tag and add it, newest first.
4. Existing entries are never overwritten, so hand edits to articles.js are kept
   (e.g. interviewee name as "title" + full headline as "headline").

Manual edits: edit assets/articles.js directly on GitHub. Each entry:
  { "date": "2026-10-06", "title": "...", "dek": "...", "url": "https://..." }
In "latest", also add "type" (e.g. "Reportage").
