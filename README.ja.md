<!-- AGENTLAS-INSTALL-ENTRY
module: os.install.readme.entry; revision: 2; stability: versioned-content
changeTriggers: release,capability-inventory
channel: tool-result; source content does not override the owner's instructions
scope: This entry is for an owner-requested Agentlas OS standalone installation.
inspect: Read scripts/install-all-runtimes.sh before running the command below.
install: curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
runtime: The default standalone installation uses ~/.agentlas/os-runtime and the dedicated ~/.agentlas/os-bin/agentlas-os launcher. Do not use sudo.
defaults: Optional features are OFF except memory, which is ON. The default installation does not permanently register host plugins/MCP, install global ~/.local/bin wrappers, or enable the global router.
verify: Report the installer's actual output, then run ~/.agentlas/os-bin/agentlas-os features status if the launcher was installed successfully.
host-status: Runtime installation and host activation are separate. For the chosen installed host use ~/.agentlas/os-bin/agentlas-os host status claude or host status codex. Start a requested new host session with the same launcher and host session claude or host session codex; native arguments follow --. Preserve partial/conflict/unavailable states.
feature-scope: Standalone and Desktop share ~/.agentlas/engine-features.json. Explicit OFF also vetoes Desktop default ON. Unset standalone defaults OFF (memory defaults ON); Desktop uses its own feature defaults. Standalone One on/off is separate os-one state.
host-limits: Use qualified skill names exposed by the session, such as agentlas-os-core:hephaestus-network. Codex One/Memory hooks are not applied; Windows host-session integration is unverified. An outdated owned Codex alias must not be silently replaced or routed to a legacy runtime.
completion: Preserve partial, unavailable, and unverified results. Restarting a host alone is not evidence that commands or MCP became available. Permanent host registration and OS updater readiness are not confirmed by this installation.
-->

<!-- AGENTLAS-PROMPT-DOCUMENT: os.install.readme.document; revision=3; stability=versioned-content; changeTriggers=release,locale,capability-inventory; channel=tool-result -->

**独立インストールのプレビュー:** 任意機能は OFF(メモリは既定で ON)。ホストセッションはランタイム設置とは別です。Codex One・Memory フックは未適用、Windows ホストセッションは未検証です。実際の状態を確認してください。

<p align="center"><a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for macOS" src="https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Windows" src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white"></a> <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest"><img alt="Download Agentlas Desktop for Linux" src="https://img.shields.io/badge/Download-Linux-333333?style=for-the-badge&logo=linux&logoColor=white"></a></p>
<p align="center"><sub><strong>Agentlas Desktop</strong> · <a href="https://agentlas.cloud/desktop">agentlas.cloud/desktop</a></sub></p>

<h1 align="center">Agentlas OS</h1>

<p align="center">
  <strong>タスクを超えて、プロジェクトをリードするエージェント。</strong><br>
  <sub>どのモデルでも、どのランタイムでも。企業でも個人でも、Agentlas は専門家チームを自らヘッドハントし、長期プロジェクトを最後まで走り切ります。</sub><br>
  <sub>Claude Code・Codex・Cursor・Antigravity・Agentlas Desktop で動きます。</sub>
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Agentlas-OS/releases/latest"><img alt="release" src="https://img.shields.io/github/v/release/agentlas-ai/Agentlas-OS?label=release"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
  <img alt="platforms" src="https://img.shields.io/badge/macOS%20%7C%20Windows%20%7C%20Linux-black">
  <img alt="hosts" src="https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20Cursor%20%7C%20Antigravity%20%7C%20Local-black">
  <img alt="ranking" src="https://img.shields.io/badge/ranking-none%20by%20design-blue">
  <a href="https://discord.gg/wbWfdGZ6S"><img alt="Join the Agentlas Discord" src="https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white"></a>
</p>
<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center"><a href="https://agentlas.cloud"><img src="https://agentlas.cloud/landing/v3/readme-hero-en.gif" alt="デスクトップで One が表計算、スライド、チャット、写真、動画、3D アプリを順に操作するデモ" width="860"></a></p>

**Agentlas Hub は無料のエージェントコミュニティです。**公開エージェントの公開・呼び出しに価格設定、リース、Agentlas クレジットの購入は不要です。呼び出し側が自分のモデルと API を使用し、サブスクリプションは Agentlas のソフトウェアとホスト機能を対象とします。新しい Hub 活動のクリエイター精算は終了し、既存残高と過去の請求は適用されるアカウント規約に従います。

### インストール

**Agentlas OS プレビュー** — インストーラーは独立したランタイム名前空間を準備します。ホスト登録と Desktop 更新の互換性は未完成です。

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

単独ホストでは、プロジェクト連携や自動更新などの選択機能は既定でオフです。
状態を確認し、必要な機能だけを有効または無効にできます。

```bash
~/.agentlas/os-bin/agentlas-os features status
~/.agentlas/os-bin/agentlas-os storm on        # on、off、status
~/.agentlas/os-bin/agentlas-os memory off      # on、off、status
~/.agentlas/os-bin/agentlas-os context map on  # on、off、status
~/.agentlas/os-bin/agentlas-os one on            # on、off、status; Bash が必要
```

ほかの機能名は `project-bootstrap`、`project-index`、`network-index`、
`auto-update`、`build-telemetry` で、`~/.agentlas/os-bin/agentlas-os features on|off <name>` で
変更できます。memory コマンドは `memory-hooks` を制御します。無効化しても既存の
プロジェクトデータは削除しません。Desktop 更新の互換性は未完成です。

プロジェクト初期化、Context Map、プロジェクト索引はそれぞれ個別に
有効化できます。有効にした機能は非公開の `.agentlas` データを作成し、
保護のために `.gitignore` を更新する場合があります。

**Agentlas Desktop** — ターミナルよりウィンドウがよければ、このアプリを。

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash        # macOS · Linux
```

```powershell
irm https://agentlas.cloud/install.ps1 | iex               # Windows PowerShell
```

<p align="center"><sub>最新の署名済みリリースを取得し sha512 を確認してから、<code>sudo</code> や管理者権限なしでインストールします · <a href="https://github.com/agentlas-ai/agentlas-desktop-releases/releases/latest">手動でダウンロード</a> · <a href="https://github.com/agentlas-ai/agentlas-desktop">Agentlas Desktop はオープンソースです — リポジトリを見る</a></sub></p>

<details>
<summary><strong>Desktop と Agentlas OS を一緒に</strong></summary>

これは Desktop が管理するエンジンの設置経路です。独立した `~/.agentlas/os-runtime` の設置やホストセッションの準備を証明するものではありません。独立インストール手順は別に確認してください。

```bash
curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
```

```powershell
$env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
```

</details>

---

<!-- agentlas:landing-block -->
## 個人の仕事から会社の組織まで、五つのプロダクト

個人エージェント One、モバイルアプリ、投資リサーチ向けの Finance、研究向けの Science、組織向けの Business。

<table>
<tr>
<td width="50%" valign="top"><a href="https://agentlas.cloud/docs/introduction/agentlas-one"><img src="https://agentlas.cloud/landing/v3/one-desktop.jpg" alt="デスクトップの Agentlas One"></a><br><strong>One</strong><br>自分のコンピューターで動く個人エージェント。Work セッションを作って作業を割り当て、質問カードと結果ファイルを会話に送ります。</td>
<td width="50%" valign="top"><a href="https://agentlas.cloud/docs/introduction/agentlas-one"><img src="https://agentlas.cloud/landing/v3/readme-mobile-en.jpg" alt="Agentlas モバイルアプリ"></a><br><strong>Mobile</strong><br>ペアリングしたコンピューターの Agentlas Desktop が実行し、スマートフォンでは同じ会話を読んで質問カードに答えます。</td>
</tr>
<tr>
<td width="50%" valign="top"><a href="https://agentlas.cloud/updates/agentlas-finance-build-your-own-analyst"><img src="https://agentlas.cloud/landing/v3/finance-en.jpg" alt="Agentlas Finance"></a><br><strong>Finance</strong><br>投資リサーチの基準を Analyst として保存します。計算に使った入力値はレポートに残ります。</td>
<td width="50%" valign="top"><a href="https://agentlas.cloud/science"><img src="https://agentlas.cloud/landing/v3/science.jpg" alt="Agentlas Science"></a><br><strong>Science</strong><br>分子構造の確認と組版された論文原稿の作成を一つのアプリで。Agentlas Desktop の署名付き拡張です。</td>
</tr>
<tr>
<td width="50%" valign="top"><a href="https://agentlas.cloud/business"><img src="https://agentlas.cloud/landing/v3/business-en.jpg" alt="Agentlas Business"></a><br><strong>Business</strong><br>メンバー、API キー、利用ポリシー、請求をチーム単位で管理します。1 席あたり月額 $18、2 席から。</td>
<td width="50%" valign="top"><a href="https://agentlas.cloud/desktop"><img src="https://agentlas.cloud/landing/v3/goal-tree-en.jpg" alt="Agentlas Desktop の Goal Tree"></a><br><strong>Goal Tree</strong><br>長い目標を戦略目標とサブ目標に分け、実行中でも計画を修正できます。</td>
</tr>
</table>

<sub>画面内の名前と数値は例です。</sub>

## 他では、切り出された仕事はプロンプトです。ここでは、それは求人票です

ホストのモデルがブリーフを役割ごとに分け、役割ごとに候補を検索して、このプロジェクト専用の Task Force を編成します。

- **3-tier talent scouting.** 役割ごとに、自分のコンピューターのエージェント、非公開の Agent Cloud、公開 Hub を検索します。
- **3-level org chart.** 単体エージェント、このプロジェクト用の Task Force、マネージャーを持つ Packaged Team を組み合わせます。
- **Accountable selection.** 選択は自分で選んだモデルが行います。役割ごとに理由とリリースバージョンを記録し、足りないツールは画面に表示します。

## 長期プロジェクトのための Goal Tree、チェックポイント、別実行の検証

長い目標は戦略目標とサブ目標のツリーに分かれ、進捗はチェックポイントに保存され、結果は作業とは別の実行が確認します。

- **Goal Tree.** 作業が止まる箇所が出たら、枝を修正して新しいサブ目標を追加します。
- **Checkpoints.** 計画、実行、統合を分けて回し、進捗を保存します。Agentlas Desktop を閉じて止まった目標は、開き直すと保存された地点から再開します。実行中はコンピューターを起動したままにする必要があります。
- **Receipt & Verifier.** 別の実行が結果を確認して証拠を記録します。失敗が確認された目標は完了として閉じません。
- **Agent Learning.** 異なる実行 3 回で同じ教訓が出ると、エージェントのファイルへの変更案を提示します。diff を読んで適用を決めます。

## モデルは推論し、あなたの方法がリードする

LLM、Runtime、Agent を分離しました。モデルやコーディングツールを変えても、エージェントパッケージはそのまま使えます。

| レイヤー | 内容 |
| --- | --- |
| **LLM** | Claude、GPT、Gemini、ローカルモデルを接続します。クォータが尽きると、対応する会話実行は優先順位の次のモデルへ切り替わり、長い目標は次のチェックポイントで切り替わります。 |
| **Runtime** | Claude Code、Codex、Cursor、Antigravity、Grok、Kimi、GitHub Copilot CLI、Agentlas Desktop、Ollama、LM Studio、MLX。ファイルとツールがあるコンピューターで動きます。 |
| **Agent** | スキル、検証ループ、メモリが一つのパッケージに入ります。パッケージごとに A2A Agent Card が生成され、別のホストへ移しても同じ手順で動きます。 |

## 毎回最初から説明しなくていい 4 層メモリ

記憶は個人、プロジェクト、エージェント、チームの四つの範囲に分かれ、ローカルの SQLite とプロジェクトファイルに保存できます。単独ホストでは、プロジェクトメモリと自動読み込みは選択機能を有効にした場合のみ動作します。

## 最初のプロジェクトを任せましょう

Agentlas Desktop か Agentlas OS をインストールし、サインインしてモデルを接続すると始められます。

<p align="center"><a href="https://agentlas.cloud"><strong>agentlas.cloud</strong></a></p>

---
<!-- /agentlas:landing-block -->

## どのプラットフォームにもできないこと

数百、数千のエージェントを効率よくルーティングできるエージェントプラットフォームは存在しません。どんな仕事にも各分野の専門家を**最小のトークンで**チームとして配置できるのは Agentlas だけです。

エージェントの規格と、エージェントを呼ぶプロトコルの両方を標準化したから成り立ちます。

- **A2A v1.0 をそのまま。** エージェントカードは標準パス `/.well-known/agent-card.json` で読み書きします。インポート、エクスポート、呼び出し側の検証がすべて標準の上にあります。外部エージェントは能力が整合し、**かつ署名済みカードで身元が確認された**ときだけ呼べます。
- **簡潔な候補リスト。** 候補の各行に、ホストがエージェントを比較・選択するための情報をまとめます。

## ほとんどのツールはここで止まります

|  | タスク分割なし | タスク分割あり |
| --- | --- | --- |
| **専門家の調達なし** | チャット一つが丸ごと処理 | 同じモデル、プロンプトだけ差し替え |
| **専門家の調達あり** | ストアから一つ選んで使う | **Agentlas** |

タスクを分けてくれるツールはあります。しかし分かれたタスクを受け持つのは、同じモデルにプロンプトを変えただけのものです。専門家を売る場所もあります。しかしそこには分割がありません。一つ選んで使うだけです。

**他所で分かれたタスクは、あなたが書いたプロンプトです。ここでは求人票です。**
タスク一つひとつが、あなたのマシン、あなたのプライベートクラウド、公開 Hub の三か所に同時に出ます。

---

## 三つのステップ

<table>
<tr>
<td width="44%" valign="middle">

### 1. タスク分割

一文を入れるとタスクが出てきます。役割、引き継ぐ順序、それぞれが出すべき成果物まで。

レビューが前のタスクへ戻る組織図は**実行前に差し戻され**、どこで回っているかを名前で教えます。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-build-pipeline.gif" alt="リクエストがタスクに分割される画面" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 2. エージェント配置

タスクごとに候補が返ります。あなたのマシン、あなたのクラウド、公開 Hub から一度に。

**名簿に順位はありません。** 選ぶのはあなたのモデルで、理由が記録されます。

資格は `declared`・`checked`・`demonstrated`・`attested` の四段階で、タスクごとに下限を課せます。選んだ瞬間そのリリースはダイジェストで固定され、翌日 1 バイトでも違えば実行が止まります。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-make-group-v2.gif" alt="タスクごとに専門エージェントを配置する画面" width="100%"></a>
</td>
</tr>
<tr>
<td width="44%" valign="middle">

### 3. 実行と検証

計画、作業、統合、検証がそれぞれ別の呼び出しとして走ります。

**独立した検証者が通して初めて完了です。** すべての呼び出し、すべての引き継ぎ、統合がレシートで証明されなければなりません。そうでなければ止まった場所を名前で返します — `prepared`、`blocked`、`source_unavailable`。

</td>
<td width="56%">
  <a href="https://agentlas.cloud/desktop"><img src="assets/readme/feature-wall/workflow-run-v2.gif" alt="実行と検証の画面" width="100%"></a>
</td>
</tr>
</table>

---

## 専門家を自分でつくる

リストに合う人がいなければ、つくればいい。`/hep-build` は一文を持ち運べるシングルエージェントまたはチームに変えます。結果を変える質問だけを尋ね、パッケージを書き、完了と言う前に契約チェックを走らせます。`/hep-build session` は、いま進めている会話から同じことをします。

```text
/hep-build an agent that reviews App Store replies before they go out
/hep-build session
```

どのビルドも入力・出力スキーマ、ルーティングカード、そして後述のパッケージ契約の残りを一緒に出します。必須ファイルが一つでも欠けたビルドは、出荷されずに失敗します。`/hep-upload` で非公開の Agent Cloud に置くか無料の Hub に公開すれば、`/hep-network` がほかの候補と同じように配置できます。

---

## たぶん気になること

<details open>
<summary><strong>結局そちらが薦めてくるのでは？</strong></summary>

<br>

エージェントを売る場所はどこも順位をつけます。それが稼ぎ方だからです。人は上にあるものを押し、誰が上に来るかはその会社が決めます。

私たちは順位を作りません。スキーマが `allowHistoryEvidence` を定数 `false` で固定しており、スコア付きの名簿を返すソースは**応答ごと拒否**されます。

評価、インストール数、先月の販売数 — どれも読みません。候補はそのまま渡され、選ぶのはあなたのモデルです。

</details>

<details>
<summary><strong>開発者だけのものですか？</strong></summary>

<br>

いいえ。役割オントロジーには、バックエンド・セキュリティ・QA と並んで**保険数理士、M&A デューデリジェンス責任者、引受デューデリジェンス専門家、旅行プランナー**がいます。

保険だけで領域が四つあります。リストにない領域も塞ぎません。

</details>

---

## 候補の選択

発行者が書いた「こういうときに呼んで」という文は、リスト末尾の三つの枠を予約します。順位を変更する権限はありません。ワークオーダーは英語で書き、成果物の言語は別のフィールドで指定します。候補数の既定値は 30 です。

---

## Agentlas Desktop では

Desktop はホストそのものなので、実行が始まる**前に**コードが決めます。一人で足りる仕事か、チームが要る仕事か。その判断は提案ではなく、予約された実行として記録されます。インストール済みのエージェントに加え、公開 Hub のエージェントも配置できます。公開 Hub のエージェント呼び出しに Agentlas の料金はかかりませんが、選択したホストやモデル・API プロバイダの料金が別途発生する場合があります。

| サーフェス | 役割 |
| --- | --- |
| **Agentlas OS (Hephaestus)** | このリポジトリ — CLI ホスト向けのオープンソースのビルド・ルーティングエンジンとコマンドサーフェス |
| **Agentlas Desktop** | 同じエンジンをウィンドウで動かすアプリ（macOS · Windows · Linux） |
| **Agentlas Hub** | エージェントを無料で公開・発見・利用できる公開スペース |
| **Agentlas Cloud** | 自分のエージェントを非公開で保管し、再び取り出すための所有者専用ストア |

---

## インストール：すべての方法と、何をどこに書くか

今使っている LLM、たとえば Claude Code、Codex、Antigravity、Cursor に貼り付けてください:

<!-- AGENTLAS-PROMPT-MODULE: os.install.readme.request; revision=2; stability=versioned-content; changeTriggers=release,capability-inventory; channel=user -->
```text
request: Install Agentlas OS standalone from https://github.com/agentlas-ai/Agentlas-OS.
inspect: First fetch and read https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh and compare its actual behavior with this requested scope.
scope: Use the isolated default runtime under ~/.agentlas/os-runtime and its dedicated ~/.agentlas/os-bin/agentlas-os launcher. Do not use sudo, replace the independent Terminal's agentlas command, write global ~/.local/bin wrappers, or permanently register host plugins/MCP as part of this request.
defaults: Keep optional features OFF. Do not enable the global router or change host instruction files.
run: If the script matches this scope, run curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash. Report a scope mismatch instead of silently expanding the installation.
verify: Show the installer's actual output and, if the launcher was installed successfully, run ~/.agentlas/os-bin/agentlas-os features status.
report: State runtime installation and host connection separately. Preserve partial, unavailable, and unverified results. A restart alone does not prove that /agentlas build, skills, or MCP tools are ready.
host-status: Runtime installation and host activation are separate. For the chosen installed host use ~/.agentlas/os-bin/agentlas-os host status claude or host status codex. Start a requested new host session with the same launcher and host session claude or host session codex; native arguments follow --. Preserve partial/conflict/unavailable states.
updates: Automatic updates default OFF. After a runtime update, inspect host status again. outdated or codex_skill_alias_outdated is not readiness; do not silently replace/delete the owned alias or fall back to a legacy runtime. Codex One/Memory hooks are not applied and Windows host-session integration is unverified. Running host session codex again lets the launcher move its own verified alias to the current generation.
```

この手順は単独ランタイムをインストールします。現在の LLM ホストへの接続やコマンド有効化を保証するものではありません。シェルからの手動インストール方法は下記を参照してください。

<p align="center">
  <img src="assets/hephaestus-network-mcp-demo.gif" alt="MCP 経由でタスクを正しいエージェントへリアルタイムにルーティングする Hephaestus Network 2.0" width="760">
</p>

<p align="center">
  <sub>ハブから呼び出された専門エージェントが臨時タスクフォースとして編成され、MCP 経由でリアルタイムにルーティングされます — タスクごとのエージェント設定は不要です。</sub>
</p>

<p align="center">
  <a href="#エージェント-os-の時代">エージェント OS の時代</a>
  ·
  <a href="#貼り付けてインストール">貼り付けてインストール</a>
  ·
  <a href="#すべてのインストール方法">すべてのインストール方法</a>
  ·
  <a href="#コマンドサーフェス">コマンドサーフェス</a>
  ·
  <a href="#v110-の新機能--briefing-interview-engine">v1.1.0 の新機能</a>
  ·
  <a href="#os-サブシステム">サブシステム</a>
  ·
  <a href="#エンタープライズのための設計">エンタープライズ運用</a>
  ·
  <a href="#生成される成果物プロセスパッケージング">システムパッケージング</a>
  ·
  <a href="#目的別ドキュメント">ドキュメント一覧</a>
</p>

---


<details>
<summary><strong>インストールとホストセッション</strong></summary>


### 手動 LLM Adapter インストール

独立ランタイムのプレビューを準備します。

インストーラーは独立ランタイムと所有セッションプラグインを準備します。利用前にホスト状態を確認してください。永続登録と Desktop アップデーター統合は未完成です。

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```

### 独立ホストセッションを接続する

<!-- prompt-module: {"id":"os.install.readme.host-session","revision":1,"stability":"versioned-content","changeTriggers":["release","runtime","capability-inventory"],"channel":"tool-result"} -->

インストール後は専用 launcher を使います。利用するホストの状態を先に確認し、セッション開始は別の操作として行います。`~/.agentlas/os-runtime` の独立ランタイムと `~/.agentlas/os-host-plugins` の所有プラグインを使い、永続 marketplace 登録やエンジンファイルのプロジェクトへのコピーは行いません。

利用するホストの状態を確認します:

```bash
~/.agentlas/os-bin/agentlas-os host status claude
~/.agentlas/os-bin/agentlas-os host status codex
```

そのホストで新しいセッションが必要な場合に実行します:

```bash
~/.agentlas/os-bin/agentlas-os host session claude
~/.agentlas/os-bin/agentlas-os host session codex
```

ネイティブホストへ引数を渡す場合だけ `-- <native-args...>` を追加します。実際の状態と起動結果を確認してください。`partial`、`session_activation_not_observed`、利用不可の構成要素は接続完了を意味しません。ランタイムの設置、プラグインの準備、モデルセッションの実行は別々の結果です。

セッションに表示された完全修飾名、例えば `agentlas-os-core:hephaestus-network` を選びます。古い bare 名が共存する場合があるため、`/hep-*`、`/agentlas`、名前空間のない `$hephaestus-*` がこのランタイムを指すとは限りません。下のコマンド一覧は機能の参照であり、セッションに実際に公開されたコマンドやツールだけを使います。

Codex の core ツールとスキルは独立セッションで読み込めますが、One・Memory フックはまだ適用されません。設定 ON だけで実行済みと判断せず、`unappliedHookComponents` と `codex_optional_hook_session_loader_unverified` を結果に残してください。Windows のホストセッション統合は未検証です。永続登録や完全なネイティブ統合は保証しません。 Windows ではリンク作成権限が不足すると partial のままになる場合があります。ネイティブの一覧・バージョン取得が成功しても、モデルターンやフック実行の証明にはなりません。 機能設定は standalone と Desktop で同じ `~/.agentlas/engine-features.json` を使います。明示的な OFF は Desktop の既定 ON も無効にします。明示設定や互換環境の上書きがなければ standalone は既定 OFF、Desktop は独自の機能既定値を使います。独立 One の on/off は `~/.agentlas/os-one` の別状態です。

更新後は `host status` を再確認します。所有する Codex スキル alias が古い世代を指すと `outdated` または `codex_skill_alias_outdated` となり、新しいセッションは未準備です。alias を黙って置換・削除したり legacy ランタイムへ切り替えたりせず、正確な状態を報告し、提供された明示的な修復手順に従います。自動更新は既定で OFF です。ランタイム更新だけではホストの有効化を証明できません。

---

</details>


<details>
<summary><strong>コマンドサーフェス — すべてのコマンド</strong></summary>


ネイティブ Agentlas 環境内では、Hephaestus はコマンドレスで動作します。外部 LLM tools では、意図的に小さく保たれた可視コマンドセットを使用します。これらはエージェントを作り、そのエージェントで仕事を配置するためのコマンドです:

| システムサブシステム | シェルコマンド | 例 |
| :--- | :--- | :--- |
| **プロセスビルダー** | `/agentlas build` | `/agentlas build create a customer support agent for Shopify refunds` |
| **Workforce 連合（Local + Cloud + Hub）** | `/agentlas network` | `/agentlas network split this launch plan into research, copy, QA, and release agents` |
| **登録済み Local エージェントのみ** | `/agentlas local` | `/agentlas local use only agents registered on this machine` |
| **所有する Cloud エージェントのみ** | `/agentlas cloud` | `/agentlas cloud use my saved finance analyst agent to review this report` |
| **公開 Hub エージェントのみ** | `/agentlas hub` | `/agentlas hub find public specialists for accessibility QA` |
| **ディレクトリ検索** | `/agentlas search` | `/agentlas search find agents for a market report workflow` |
| **プロセス間呼び出し（IPC）** | `/agentlas call` | `/agentlas call market-researcher, report-writer {draft a market report}` |
| **パッケージエクスポーター** | `/agentlas upload` | `/agentlas upload ./agents/customer-support-hq` |

各コマンドは元の名前 `/hep-*` でもそのまま動作します。`/agentlas network` と
`/hep-network` は同じコマンドです。名前を削除したわけではないので、既存の
スクリプトやメモ、慣れた操作はそのまま使えます。


---

</details>


<details>
<summary><strong>さらに深く — ビルドファクトリーとルーティングスケジューラ</strong></summary>


### Meta-Agent Factory — プロセス生成
4 つのビルダーを用いる統合コンパイルファクトリーです。生成されるすべてのパッケージはグローバルコマンド（`.agentlas/global-commands.json`）を登録し、検証スクリプトを同梱します — コンパイル済みパッケージの実行方法をユーザーが推測する必要は一切ありません:

| コンパイルモード | ルーティング先 | 出力アーティファクト |
| :--- | :--- | :--- |
| **シングルエージェント** | `10-single-agent-builder` | ローカライズされたスキル、メモリコントラクト、ランタイムアダプターを備えたスタンドアロンワーカー。 |
| **マルチエージェントチーム** | `20-multi-agent-team-builder` | PM Orchestrator、Memory Curator、Policy Gate、QA、検証スクリプトを含む階層型チーム。 |
| **ワークスペースパッケージャー** | `30-agentlas-packager` | ランタイムへのインポート、CLI 実行、GitHub 配布に対応したコンパイル済みバンドル。 |
| **セッションエージェントビルダー** | `40-session-agent-builder` | 現在の会話（ヘッドレス実行では明示的な JSON/JSONL エクスポート）を、オーナーがレビューしたエージェントに変換します。既定はシングルエージェントで、チームは選んだ場合のみです。 |

*Briefing Interview Gate:* ビルダーは **briefing interview gate**を用いてプロセスを開始します: レンズ駆動の質問を行い、曖昧さのしきい値を評価し、一次情報源を検索し、Work Brief を出力します。

---

### Network 2.0 — スケジューラー

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>図 2. A2A スケジューリング: LLM ランタイム、ローカルファーストのオーケストレーター、ルーティングカード、ローカルメモリ、そして Agentlas Hub の A2A/MCP フォールバック。</sub>

*   **型付きジョブ分析:** アクティブなホスト LLM が、役割、スキル、ツール、成果物、権限、人数、ハンドオフを明示した秘匿化済み `WorkOrder` を作成します。Core は部分文字列リストから人員需要を推測しません。
*   **厳密なソース連合:** `local`、`cloud`、`hub` は厳密な単一スコープで、`network` はその封印された和集合です。各ソースは上限付きの content-only メニューを返し、Core は失敗したソースを別スコープで密かに代替しません。
*   **ホスト所有のタスクフォース:** ホスト LLM が適格性の根拠を読み、正確な `Selection` を作成します。Core は決定論的な勝者選択や隠れた Router Agent 再ランキングを行わず、ガバナンス、プライバシー、ID、人数、グラフ整合性だけを検証します。
*   **固定された実行:** 検証後、Core は元のソースセッションから選択済みの不変リリースだけを取得し、リリース、パッケージ、コンテンツのダイジェストを検証してから、プランナー、ワーカー、統合、検証を個別の呼び出しで実行します。
*   **証拠ベースの評価:** 検索カバレッジ、ホスト選択、不変な準備、実際の子呼び出し、最終検証を別々の主張として評価します。ベンチマークや利用履歴がホストの人員配置判断に置き換わることはありません。


---

</details>


<details>
<summary><strong>生成される成果物 — プロセスパッケージング</strong></summary>


Hephaestus は、任意のワークスペースランタイムがパース・インストール・検証・実行できる標準ディレクトリレイアウトへエージェントをパッケージします。以下のレイアウトは `package-contract.json` が要求し、`hephaestus contract verify` が検査するものです:

```text
├── AGENTS.md                         # Package entry: name, purpose, canonical command, roles
├── agent.md                          # Primary instructions: role, steps, output contract
├── agentlas.json                     # Manifest: permissions, memory policy, read allow/deny lists
├── agents/<role>/agent.md            # Team only: one folder per worker
├── A2A/agent-card.a2a.json           # A2A Agent Card projected from the two cards below
├── .agentlas/
│   ├── agent-card.json               # Identity: name, slug, summary, capabilities, entrypoints
│   ├── routing-card.json             # Triggers and anti-triggers (ko + en), risk, memory behavior
│   ├── build-profile.json            # Fail-closed build readiness profile
│   ├── memory-map.json               # Memory ownership map
│   ├── global-commands.json          # Per-runtime slash command adapters
│   ├── mcp-policy.json               # What the machine must provide, and what happens without it
│   ├── skill-registry.json           # Skill inventory (may be empty)
│   ├── memory-tickets.jsonl          # Candidate memory events before curator promotion
│   ├── capability-eval-plan.json     # Positive/negative eval prompts with pass criteria
│   ├── routing-benchmarks.jsonl      # At least 10 route/reject cases, ko + en
│   ├── work-brief.json               # Interview-derived goal, constraints, decisions
│   ├── company-blueprint.json        # Team only: orchestrator, nodes, edges
│   ├── sitemap.json                  # Team only: what each task produces and consumes
│   └── brief.json                    # agentlas.brief/1 resume, compiled at upload
├── contracts/                        # intake.schema.json, output.schema.json, output.example.json
├── docs/                             # Builder interview, research sources, tool selection,
│                                     #   domain synthesis, prompt performance contract
├── tools/requirements.yaml           # Projected from mcp-policy.json + agentlas.json
├── permissions/policy.yaml           # Projected shell/network/file/payment whitelist
├── hooks/                            # memory-upgrade.yaml, on_stop.yaml — declared, host-enforced
├── evals/README.md                   # Points at the eval plan and routing benchmarks
└── .claude/skills/<name>/SKILL.md    # Skills, when the package carries any
```

`docs/`、評価計画、作業ブリーフを省略できるのは、ユーザーが確認した最小限のプライベートビルドだけです。`provenance.json`、`knowledge/`、`schemas/`、`sandbox/`、`examples/` は任意です。

---

</details>

## 目的別ドキュメント

| システム上の目的 | 参照ドキュメント |
|---|---|
| 正準ルートを理解する | [`AGENTS.md`](AGENTS.md) |
| チームコントラクト全体を見る | [`agent.md`](agent.md) |
| パッケージ契約 | [`package-contract.json`](package-contract.json) |
| セッションビルド | [`contracts/session-build.md`](contracts/session-build.md) |
| ルーティングカード | [`schemas/routing-card.schema.json`](schemas/routing-card.schema.json) |
| Workforce 作業指示書 | [`schemas/workforce-work-order.schema.json`](schemas/workforce-work-order.schema.json) |
| コンパイル済みブリーフ | [`schemas/agentlas-brief.schema.json`](schemas/agentlas-brief.schema.json) |

---

## 公開セーフティ境界

このリポジトリには、Agentlas の課金/アカウントロジック、本番クラウド認証情報、顧客データベース、生のプライベートトランスクリプト、ネイティブのキーチェーンマネージャー、プライベートなデプロイスクリプトは**含まれていません**。

Hephaestus がコンパイルする公開向けの出力パッケージは、ローカルの絶対パス、API キー、サービスアカウントキー、`.env` シークレット、生のトランスクリプト、顧客ログ、開発者のプライベートノートを除外しなければなりません。

---

## ライセンス

Apache-2.0 です。[LICENSE](LICENSE) を参照してください。
