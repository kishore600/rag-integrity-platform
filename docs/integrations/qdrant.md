# Draft: a RAGGuard page for Qdrant's documentation

Qdrant's documentation has pages for tools that work with Qdrant. Its source is the GitHub repository `qdrant/landing_page`, folder
`qdrant-landing/content/documentation/frameworks/`, next to pages such as `deepeval.md` (another tool for checking RAG).

The page is ready in [qdrant-page.md](qdrant-page.md): copy the whole file, including the `---` block at the top (Qdrant's site
reads the title and descriptions from it).

## Send it as a pull request (in the browser, about 15 minutes)

1. Sign in to GitHub as the account that owns RAGGuard.
2. Open https://github.com/qdrant/landing_page/tree/master/qdrant-landing/content/documentation/frameworks
3. "Add file", then "Create new file". Name it `ragguard.md` and paste the page.
4. "Commit changes...", then "Propose changes", then "Create pull request". GitHub makes your copy (fork) of their repository for
   you.
5. Title: `Add RAGGuard to frameworks`. Description, in your own words: what RAGGuard checks, that it only reads the collection,
   and that you built it.
6. If a bot asks you to sign a contributor agreement (CLA), follow its link and sign. Answer the maintainers' comments; they may ask
   you to add the page to a menu or change the format.
