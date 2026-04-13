# codex-practice

## Pushing a Local Repo to GitHub

GitHub's **Import repository** page (`github.com/new/import`) only works for repos
hosted on another git server (GitLab, Bitbucket, Azure DevOps, etc.). It requires
an internet-accessible URL — you **cannot** use it for a local repo on your machine.

For a **local repo**, use the `push-to-github.sh` script in this repo:

```bash
# From inside your local project directory:
bash /path/to/push-to-github.sh https://github.com/yourname/your-repo.git
```

### Manual steps (without the script)

1. Create a new **empty** repo on GitHub (no README, no .gitignore): `https://github.com/new`
2. In your terminal, navigate to your local project:
   ```bash
   cd /path/to/your/project
   ```
3. If not already a git repo:
   ```bash
   git init
   git add -A
   git commit -m "Initial commit"
   ```
4. Add GitHub as the remote and push:
   ```bash
   git remote add origin https://github.com/yourname/your-repo.git
   git push -u origin main
   ```

### When to use GitHub Import

Use `github.com/new/import` only when the source repo is hosted at a URL
that GitHub can reach — e.g. a GitLab or Bitbucket repository.
