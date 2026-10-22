# cv-forge

cv-forge is a job-search copilot: it keeps one master profile of everything you have done, tailors an honest, ATS-safe LaTeX CV and cover letter for each real job posting, and prepares the application kit, while you always click submit yourself.

Work in progress. Full documentation arrives with the first release.

Built on [ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) (MIT).

## Enable the hooks

Privacy and attribution guards run as git hooks (private paths, denylisted terms, CPF/phone numbers, em dashes, AI attribution in messages):

```bash
git config core.hooksPath .githooks
```
