# README Pattern Analysis

Snapshot date: 2026-06-04

Source method: GitHub Search API, sorted by stars descending, top 10 repositories.

## Repositories Reviewed

| Rank | Repository | README |
|---:|---|---|
| 1 | `codecrafters-io/build-your-own-x` | https://github.com/codecrafters-io/build-your-own-x/blob/master/README.md |
| 2 | `sindresorhus/awesome` | https://github.com/sindresorhus/awesome/blob/main/readme.md |
| 3 | `freeCodeCamp/freeCodeCamp` | https://github.com/freeCodeCamp/freeCodeCamp/blob/main/README.md |
| 4 | `public-apis/public-apis` | https://github.com/public-apis/public-apis/blob/master/README.md |
| 5 | `EbookFoundation/free-programming-books` | https://github.com/EbookFoundation/free-programming-books/blob/main/README.md |
| 6 | `openclaw/openclaw` | https://github.com/openclaw/openclaw/blob/main/README.md |
| 7 | `nilbuild/developer-roadmap` | https://github.com/nilbuild/developer-roadmap/blob/master/readme.md |
| 8 | `donnemartin/system-design-primer` | https://github.com/donnemartin/system-design-primer/blob/master/README.md |
| 9 | `jwasham/coding-interview-university` | https://github.com/jwasham/coding-interview-university/blob/main/README.md |
| 10 | `vinta/awesome-python` | https://github.com/vinta/awesome-python/blob/master/README.md |

## Patterns Worth Applying

### 1. First Screen

Common pattern:

- logo or banner;
- project name;
- one-line promise;
- badges or quick credibility markers;
- primary navigation links.

Applied in this repo:

- banner linked to `agentlas.cloud`;
- short `agentlas-meta-agent` title;
- one-line promise;
- release, license, runtime, and package badges;
- quick nav to Quick Start, what it builds, install, compare, docs, and languages.

### 2. Quick Start Before Theory

Common pattern:

- top READMEs show the fastest path before deep explanation;
- CLI-centric projects put install commands close to the top;
- expected output or verification appears near the install command.

Applied in this repo:

- Claude Code, Codex, and generic terminal install are now directly under Quick Start;
- `/reload-plugins` and `plugin list` are shown for Claude Code;
- `codex plugin list` appears before and after install.

### 3. Goal-Based Navigation

Common pattern:

- large repos avoid one long undifferentiated essay;
- readers can jump to tutorials, categories, docs, contribution, or security sections.

Applied in this repo:

- `Docs By Goal` maps common user intent to exact files;
- `What It Builds` maps user asks to router agents and outputs;
- localized quick starts stay short instead of duplicating the full README five times.

### 4. Categories And Use Cases

Common pattern:

- list-style repos win by giving readers a visible map of categories;
- educational repos show what the reader can build or learn.

Applied in this repo:

- single-agent, team-builder, and packager modes are shown as the primary categories;
- output repo structure is shown as a concrete tree;
- example prompts show how to use the package.

### 5. Trust And Maintenance Signals

Common pattern:

- top READMEs include contribution, security, license, translation, or community guidance;
- successful READMEs separate public project boundaries from private operational details.

Applied in this repo:

- verification and public-safety scripts are visible;
- public-safety boundary is explicit;
- contribution and license sections are retained.

## Intentional Differences

This repo is not an awesome list or a curriculum, so the README should not become a huge catalog. The better fit is a developer-tool README:

1. show the name and promise;
2. show install commands;
3. show what it builds;
4. show how it compares;
5. route deeper readers into docs.
