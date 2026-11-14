---
title: Publishing studies
description: A private gallery with every study, and a public one generated from it.
---

A project keeps all its studies in a **private gallery**, published or not, and publishes some
of them in a **public gallery**, a separate repository generated from the private one and never
edited by hand.

## What may go public

A study goes public when its `study.yml` says `public: true` and `gallery check` finds nothing
against it:

- a `result` (a novel result a paper will use) needs its `preprint`; verification, method,
  example and benchmark studies may go at once;
- it uses none of the `private_codes` of `gallery.yml`, so the public site and its CI need no
  access to private repositories;
- it imports no helper module of the repository, since only its folder is copied;
- it is not a stub.

Files of the study named by `exclude` stay private; smoke results are never copied.

## Set-up

In the private gallery's `gallery.yml`:

```yaml
public:
  owner: spokes3d
  repo: gallery
  title: SPOKES3D gallery
  description: Studies of spokes in magnetrons, and the verification of the codes.
  overlay: public   # files copied into the public repository, e.g. its home page
```

Once:

1. Create the public repository, empty, and give it a `devel` branch.
2. Make a deploy key (`ssh-keygen -t ed25519 -N "" -f deploy_key`): the public half goes to
   the public repository (Settings, Deploy keys, **allow write access**), the private half to
   the private gallery as the secret `PUBLIC_GALLERY_DEPLOY_KEY`.
3. In the public repository, allow GitHub Actions to create and approve pull requests
   (Settings, Actions, General), enable Pages (source "GitHub Actions") and let the
   `github-pages` environment deploy from `devel` (Settings, Environments).
4. In the private gallery, add `.github/workflows/sync.yml`:

   ```yaml
   name: Sync public studies
   on:
     push: { branches: ["devel"] }
     workflow_dispatch:
   jobs:
     sync:
       uses: spokes3d/gallery-template/.github/workflows/sync.yml@devel
       secrets:
         deploy-key: ${{ secrets.PUBLIC_GALLERY_DEPLOY_KEY }}
   ```

## What happens

On every push to the private gallery's `devel`, the sync runs `gallery export` into a checkout
of the public repository. If the public studies changed, it pushes the export to the public
branch `sync`, and the public repository opens a pull request into `devel` (or updates the open
one). Its checks run the studies' smoke presets and build the site from the cached results.
When all of them pass, the public repository's `sync_merge.yml` merges the pull request and
deploys the site: the changes were reviewed in the private gallery, so the export goes out
without a second review. A failing check leaves the pull request open, to fix in the private
gallery.

The export holds the public studies with their cached results, a `gallery.yml` and a
`pyproject.toml` with the codes they use, the site, the workflows and `.gallery-export.json`
with the source commit. No secret reaches the public repository: the deploy key can write to
it, and nothing in it can read the private one.

To try an export by hand:

```bash
uv run gallery export ../gallery   # empties ../gallery, keeps .git, .venv and node_modules
```
