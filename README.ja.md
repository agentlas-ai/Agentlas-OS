<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — Network 2.0</h1>

<p align="center">
  <strong>ローカルファーストのエージェント &amp; プラグイン・ネットワーキング: どの AI ランタイムからでも自分のエージェントを呼び出し、標準化されたルーティングカードでルーティングし、メモリは手元のマシンに保持します。</strong>
</p>

<p align="center">
  ラフな agent アイデア 1 つを、インストール可能な Agentlas agent/team リポジトリに変換します — その後は Hephaestus Network がすべてのリクエストを適切なローカル agent にルーティングし、Hub へのフォールバックはあなたの承認がある場合のみ行われます。
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="README.ko.md">한국어</a>
  ·
  <a href="README.zh-CN.md">中文</a>
  ·
  <a href="README.ja.md">日本語</a>
  ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Agentlas Meta-Agent architecture decomposition">
</p>

---

## Hephaestus Network 2.0

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Hephaestus Network 2.0 A2A networking architecture">
</p>

<p align="center">
  <sub>図2. Hephaestus Network 2.0 — ランタイム、グローバルなローカルファースト・オーケストレーター、ルーティングカード、承認ゲート、ローカルメモリ、そして Agentlas Hub の A2A/MCP フォールバック。</sub>
</p>

ひとつのコマンドで、すべてのランタイムから、すべてローカルで:

```text
/hep-network 会議メモを週次レポートにまとめて
/hep-network 新製品のローンチ計画を下書きして
@Hephaestus このフォルダの文書を整理して要約して   # スラッシュコマンド非対応ランタイム
hep-network "このタスクに合うエージェントを探して"   # ターミナル
```

- **ルーティングカード。** すべての agent、team、plugin は、標準化された
  ルーティングカード（トリガー、アンチトリガー、capabilities、リスク
  プロファイル、メモリ動作）を同梱します。品質ゲートを通らないカードが
  自動ルーティングされることはありません。
- **ローカルファースト。** 明示的なコマンド → プロジェクトのオーバーライド →
  手元のローカルカード、の順で解決します。Agentlas Hub はフォールバックで
  あり、送信されるのは redact 済みのキーワードだけです — 生のプロンプトが
  送られることはありません。
- **メモリはローカルに残ります。** agent の能力は Hub から取得できますが、
  user/project メモリは `~/.agentlas/networking/` にあり、明示的なエクスポート
  承認なしにマシンの外へ出ることはありません。
- **レシート、実行ではありません。** すべてのルーティング決定はレシートを
  書き込みます。Router は agent または Hub bundle を選ぶだけで、実際の
  tool permission は host runtime が扱います。
- **主張ではなく計測。** ルーティングベンチマーク（韓国語 + 英語）が自動
  ルーティングをゲートします: top-3 recall ≥ 90%、プライバシースイートで
  unsafe route ゼロ。

詳細: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) ·
ランタイム対応マトリクス: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

## 貼り付けてインストール (AI にやってもらう)

ターミナルが苦手でも、自分で何か実行する必要はありません。AI コーディング
ツール（**Claude Code・Codex・Gemini CLI・Antigravity・Cursor** のどれでも）を
開き、次のメッセージをチャット欄にそのまま貼り付けてください。エージェントが
代わりにインストーラーを実行し、次に使うコマンドを教えてくれます。

```text
このワークスペースに Hephaestus Agentlas メタエージェントをセットアップして。GitHub リポジトリはこちら:
https://github.com/agentlas-ai/Hephaestus

最新リリース/インストール手順に従い、私が使っているツール（Claude Code, Codex, Gemini CLI, Antigravity, Cursor）で使うコマンドを教えて: /hep-build, /hep-network, /hep-cloud, /hep-search, /hep-call, /hep-upload。失敗したらエラーを読んで直し、もう一度試して。
```

終わったら 3 つだけ覚えれば十分です。作成は `/hep-build`、Hub から
借りるときは `/hep-network`、自分の Agentlas Cloud に保存した agent は
`/hep-cloud`。アップロードは `/hep-upload` で、private Cloud か public Hub かを先に確認します。
自分でコマンドを実行したい場合は、下の **Quickstart** を使ってください。

---

## Quickstart

インストール方法は 3 つあります。Agentlas のフルローカル runtime が必要なら **1 + 3** を使います。Claude Code、Codex、通常の project folder にこの package だけを直接入れたい場合は **2** を使います。

| パス | 向いている用途 | 何を開くか |
|---|---|---|
| 1. Agentlas Terminal | shell から Agentlas agents を実行する | 先に Agentlas Desktop、その後 macOS Terminal / Windows PowerShell / Linux terminal |
| 2. Hephaestus standalone | Claude Code、Codex、通常 repo に直接入れる | Claude Code、Codex、または OS terminal |
| 3. Agentlas Desktop | visual local runtime、agent/team 管理、vault、Apps | browser で download し、Agentlas Desktop app を開く |

### 1. Agentlas Terminal をインストール

Agentlas Terminal は **Agentlas Desktop** からインストールします。Desktop を入れた後、app 内で次を開きます。

```text
Agentlas Desktop -> Settings -> Use from the terminal (`agentlas` CLI) -> Install CLI
```

その後、通常の terminal を開いて `agentlas` を実行します。

**macOS Terminal**

```bash
arch=$([ "$(uname -m)" = "arm64" ] && echo arm64 || echo x64)
curl -fL "https://agentlas.cloud/api/desktop/download?arch=${arch}" -o Agentlas.dmg
open Agentlas.dmg
```

**Windows PowerShell**

```powershell
$r = Invoke-RestMethod https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest
$u = ($r.assets | Where-Object { $_.name -like '*Windows-x64-Setup.exe' }).browser_download_url
Invoke-WebRequest $u -OutFile "$env:TEMP\AgentlasSetup.exe"
Start-Process "$env:TEMP\AgentlasSetup.exe"
```

**Linux terminal, AppImage**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest \
  | grep -o 'https://[^"]*Linux-x64\.AppImage' | head -1)
curl -fL "$url" -o Agentlas.AppImage
chmod +x Agentlas.AppImage
./Agentlas.AppImage
```

**Linux terminal, Debian/Ubuntu**

```bash
url=$(curl -fsSL https://api.github.com/repos/agentlas-ai/agentlas-desktop/releases/latest \
  | grep -o 'https://[^"]*Linux-x64\.deb' | head -1)
curl -fL "$url" -o agentlas.deb
sudo dpkg -i agentlas.deb
```

Desktop Settings で CLI をインストールした後:

```bash
agentlas list
agentlas run agentlas-meta-agent "Package this workflow for Agentlas"
```

### 2. Hephaestus を standalone でインストール

#### Simple file install

package files を入れたい project folder で macOS Terminal、Linux terminal、Windows Git Bash、または WSL を開きます。

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install.sh | bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Windows PowerShell:

```powershell
$zip = "$env:TEMP\hephaestus-main.zip"
$extract = "$env:TEMP\hephaestus-main"
Invoke-WebRequest "https://github.com/agentlas-ai/Hephaestus/archive/refs/heads/main.zip" -OutFile $zip
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $extract -Force
$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Copy-Item -Destination (Get-Location) -Recurse -Force
```

#### Claude Code plugin install

marketplace 登録と plugin install は別の手順です。marketplace command は Claude Code にこの repo の場所を教えるだけで、install command が実際に plugin を入れます。インストール後は reload します。

**Claude Code chat の中で入力**:

```text
/plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
/plugin install hephaestus@agentlas-core-engine
/reload-plugins
/plugin list
```

**`claude` CLI が使える OS terminal で入力**:

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

期待される結果:

```text
✓ Installed hephaestus. Run /reload-plugins to apply.
Reloaded: 1 plugin · 0 skills · 9 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

#### Codex plugin install

Codex chat の中では `/plugin marketplace add` は使いません。Codex app では `/plugins` で installed plugins を確認し、install は OS terminal で実行します。

**`codex` CLI が使える OS terminal で入力**:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus
codex plugin list
codex plugin add hephaestus@agentlas-core-engine
codex plugin list
```

Codex がすでに開いている場合は、新しいチャットを開始して `/plugins` で plugin が見えることを確認してください。インストール後は `/prompts:hep-build ontology` を実行します。

### 3. Agentlas Desktop をインストール

browser で次を開きます。

```text
https://agentlas.cloud/desktop
```

Desktop は local projects、agents、teams、Apps、vault references、runtime selection、built-in Core Engine Meta-Agent routing、`agentlas` CLI installer を提供します。

## 画像で見るインストール手順

すでに Claude Code chat の中にいる場合は Claude slash command の画像を使います。Codex は先に OS terminal で install し、Codex app の中では `/plugins` で installed plugins を確認します。macOS Terminal、Windows PowerShell、Linux terminal、Git Bash、WSL を開いている場合は CLI の画像を使います。

### Claude Code chat

Claude Code にそのまま入力します。

![Claude Code chat install flow](assets/install-claude-code-chat.svg)

### OS terminal の Claude CLI

shell で `claude` command が使える場合はこちらです。

![Claude CLI install flow](assets/install-claude-cli.svg)

### Codex app plugin browser

OS terminal で `codex plugin ...` install を終えた後、Codex app で `/plugins` と入力して確認します。

![Codex app plugin browser](assets/install-codex-chat.svg)

### Codex Desktop または IDE Extension

Codex に Plugins settings 画面がある場合はこちらです。

![Codex Desktop settings install flow](assets/install-codex-desktop-settings.svg)

### OS terminal の Codex CLI

shell で `codex` command が使える場合はこちらです。

![Codex CLI install flow](assets/install-codex-cli.svg)

## 何を開き、どこに入力するか

| 作業 | 開くもの | 入力先 |
|---|---|---|
| Desktop を download | browser | `https://agentlas.cloud/desktop` または OS 別 download command |
| `agentlas` CLI を install | Agentlas Desktop | Settings -> Use from the terminal -> Install CLI |
| Agentlas Terminal を実行 | OS terminal | `agentlas list`, `agentlas run ...` |
| Claude plugin を slash command で install | Claude Code | `/plugin marketplace add ...`, `/plugin install ...`, `/reload-plugins` |
| Claude plugin を shell で install | OS terminal | `claude plugin marketplace add ...`, `claude plugin install ...` |
| Installed Codex plugins を確認 | Codex app | `/plugins` |
| Codex plugin を shell で install | OS terminal | `codex plugin marketplace add ...`, `codex plugin add ...` |

## 何を生成するか

Hephaestus は prompt だけを返すものではありません。他の runtime が読めて、install できて、verify できて、継続的に改善できる repository を残します。

| 依頼 | ルート | 結果 |
|---|---|---|
| "X を行う agent を作って" | `10-single-agent-builder` | skills、memory contracts、runtime adapters、verification を持つ single worker |
| "この workflow の team/company を作って" | `20-multi-agent-team-builder` | HQ、PM Soul、Memory Curator、Policy Gate、eval、QA、handoff を持つ multi-agent team |
| "既存 agent/repo/workspace を package して" | `30-agentlas-packager` | Desktop import、terminal、Codex、Claude、Gemini、public GitHub release に対応した Agentlas package |

## v0.7.20 の新機能

- **短い command surface。** Claude Code、Codex、Gemini CLI、Antigravity、Cursor、OpenCode、terminal install は `/hep-build`、`/hep-network`、`/hep-cloud`、`/hep-search`、`/hep-call`、`/hep-upload` を同じ形で公開します。
- **明示的な upload gate。** `/hep-upload` は package、publish、register、upload を行う前に、private Agentlas Cloud か public Agentlas Hub かを必ず確認します。
- **よりクリーンな install。** 新規 install と update は古い `/hephaestus-*` chat command files を整理しつつ、古い terminal caller との互換性を維持します。

## Architecture

public core は architecture/foldering contract です。Claude、Codex、Gemini、Desktop、Terminal folders は同じ core の上にある thin adapters であり、別の source of truth ではありません。

| Public contract | 役割 |
|---|---|
| Mode auto-detection | `single-agent-creator`、`team-builder`、`agentlas-packager` のどれかを先に選びます。 |
| Clarify question loop | runtime、public/private boundary、tools、safety に影響する質問だけをします。 |
| `.agentlas` auto-activation | local runtime が project memory、sitemap/task-bias、Memory Tickets、vault references を seed できるようにします。 |
| Skill lifecycle registry | skill を candidate metadata として開始し、trial ledger と Curator decision ledger を保持します。 |

default export は保守的です。生成された skill は自動で first-class recall になりません。Curator が execution evidence、sealed holdout/replay、rollback、workspace policy approval を確認してから昇格します。

## Agentlas Desktop と Terminal を併用する利点

- Desktop で agent/team structure、local projects、Apps、vault references、runtime choices を確認できます。
- Terminal では同じ package を `agentlas` command で実行できます。
- Desktop/Terminal には Core Engine Meta-Agent path が内蔵されているため、別途 standalone plugin を入れなくても agent creation/package work を開始できます。
- standalone Claude/Codex install は、その runtime に package を直接入れたい場合に有効です。

## Compare

| 比較対象 | 強み | Hephaestus が追加するもの |
|---|---|---|
| OpenAI / Codex | 強力な model と coding terminal | portable repo contracts、`.agentlas` memory/package files、skills、schemas、runtime adapters、public verification |
| Claude / Claude Code | 強力な reasoning と Claude-native workflow | Claude-only ではなく、Codex、Gemini、Desktop、Terminal、`AGENTS.md` も揃えます |
| OpenClaw | local identity と workspace agent loop | visible role folders、Agentlas package contracts、public-safety checks、Desktop import、vault references |
| Hermes | persona と memory-centered local runtime | PM Soul、Memory Tickets、sitemap/task-bias、policy/eval/QA、skill lifecycle evidence |

OpenAI と Claude は model/runtime surfaces です。OpenClaw と Hermes は local-agent experiences です。Hephaestus は agent を portable、inspectable、installable、publishable にする package layer です。

## 使い方

```text
/meta-agent Create a research agent for SEC filing analysis.
Package it for Codex, Claude Code, Gemini, and Agentlas Desktop.
```

```text
Use Hephaestus.
Build a customer-support operations team with PM Soul, Memory Curator, Policy Gate, QA, eval, and public-safe release checks.
```

```text
Package this local OpenClaw/Hermes-style workspace into Agentlas architecture.
Keep private notes, machine paths, raw logs, and secrets out of the public repo.
```

## Docs

| 目的 | 文書 |
|---|---|
| canonical route を理解する | [`AGENTS.md`](AGENTS.md) |
| team contract を見る | [`agent.md`](agent.md) |
| source of truth を見る | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| runtime boundaries を理解する | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| mode を選ぶ | [`docs/mode-classifier.md`](docs/mode-classifier.md) |
| package を verify する | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| public safety を check する | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

## Public Safety Boundary

この repo には hosted Agentlas billing/account logic、production credentials、customer data、raw private logs、raw transcripts、desktop keychain storage、local database implementation、private deployment configuration を含めません。

public package には local machine paths、API keys、tokens、private keys、service-account JSON、`.env` secrets、private research notes、raw chat transcripts、customer logs、hosted billing/account/OAuth internals、desktop storage internals を入れないでください。

## License

Apache-2.0。詳しくは [`LICENSE`](LICENSE) を確認してください。
