---
description: Push changes to GitHub repository
---

# Push Changes to GitHub

This workflow automatically commits and pushes all changes to the Bunny-run repository.

## Steps

// turbo-all

1. **Check Git Status**
```bash
git status
```

2. **Add All Changes**
```bash
git add .
```

3. **Commit Changes**
```bash
git commit -m "Update: Auto-commit from Antigravity"
```

4. **Push to GitHub**
```bash
git push origin main
```

## Notes

- The `// turbo-all` annotation allows all steps to auto-run
- Changes are committed with a default message
- If you want a custom commit message, you can modify step 3
- Make sure you're on the correct branch before pushing
