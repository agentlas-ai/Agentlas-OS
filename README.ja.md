<p align="center">
  <a href="https://agentlas.cloud">
    <img src="assets/agentlas-agent-lab-banner.svg" alt="Agentlas Agent Lab banner">
  </a>
</p>

<h1 align="center">Hephaestus — モデル非依存のエージェント OS</h1>

<p align="center">
  <strong>タスクのたびにエージェントを作って設定し直すのは、もうやめましょう。Hephaestus は専門エージェントをハブに蓄え、タスクごとに一時的なオーケストレーターをその場で生成します。</strong><br>
  ローカルファーストで、どのモデルとも組み合わせられます — Claude Code、Codex、Gemini、Cursor、ローカルモデルに対応。
</p>

<p align="center">
  <a href="https://github.com/agentlas-ai/Agentlas-OS/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/agentlas-ai/Agentlas-OS?label=release">
  </a>
  <a href="LICENSE">
    <img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green">
  </a>
  <img alt="LLMs" src="https://img.shields.io/badge/LLMs-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20%7C%20Antigravity%20%7C%20Cursor%20%7C%20DeepSeek%20%7C%20GLM%20%7C%20Ollama-black">
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="README.ko.md">Korean</a>
  ·
  <a href="README.zh-CN.md">中文</a>
  ·
  <a href="README.ja.md">日本語</a>
  ·
  <a href="README.hi.md">हिन्दी</a>
</p>

## 貼り付けてインストール

今使っている LLM、たとえば Claude Code、Codex、Gemini CLI、Antigravity、Cursor に貼り付けてください:

```text
この GitHub リポジトリから Hephaestus をインストールしてください:
https://github.com/agentlas-ai/Agentlas-OS

plugin marketplace に登録して plugin としてインストールし、
次の session から Hephaestus plugin と commands が使えるようにしてください。
global routing をサポートしている場合は、それも有効にしてください。

最後に、有効になった plugin、command surface、global routing の状態を確認してください。
```

すでに使っている LLM の中で Hephaestus をすぐ有効化したいときに使ってください。
shell で手動インストールする場合は、下の全インストール方法を参照してください。

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

## エージェント OS の時代

業界はすでに、ステートレスでその場しのぎの「ツール付きチャットボット」の段階を越えました。Google をはじめとする主要 AI ラボが開発者戦略を**エージェントオペレーティングシステム**（Antigravity オーケストレーションプラットフォームや Gemini Spark デーモンプロセスなど）を軸に再構成する中で、AI エージェントは正式にオペレーティングシステムの第一級プリミティブ — 固有のアイデンティティ、リレーショナルなメモリシステム、セキュリティ権限、ネイティブなツール呼び出し環境を備えた、長寿命でステートフルなプロセス — になりました。

これにより、チームにとって決定的なエンジニアリング上の問いはこう変わります。**あなたのワークフォースは、誰のオペレーティングシステム上で動いているのか?**

エージェントが単一のモデルプロバイダーの独自 API に密結合していると、組織のメモリ、カスタムツール、タスク固有のロジックは、事実上そのベンダーのエコシステムにロックインされます。

**Hephaestus は、独立したモデル非依存のカーネルです。** エージェントフレームワークでも API ラッパーでもありません。ローカルファーストのエージェントオペレーティングシステム — 任意の LLM ランタイム上でポータブルなエージェントプロセスをコンパイルし、スケジューリングし、統制する、統合された実行基盤です。基盤となる推論エンジンを差し替えても、ワークフォース全体はそのまま維持されます。

Hephaestus は、古典的なオペレーティングシステムの概念に直接対応します:

| OS の抽象概念 | Hephaestus における実装 |
| :--- | :--- |
| **カーネル / Policy Gate** | 決定的ルーター + セキュリティゲート。すべてのルーティング動作は監査可能なレシートを生成し、ツール実行権限は厳密にサンドボックス化され、アクティブなランタイムによって強制されます。 |
| **プロセス / スレッド** | 明示的で型付けされたコントラクト（Routing Card、アンチスコープ、メモリ境界、検証シム）を持つパッケージとしてコンパイルされる、独立したエージェントとマルチエージェントチーム。 |
| **プロセススケジューラー** | Network 2.0 ルーティング（ローカルファースト、品質ゲート、ベンチマークゲート付きディスパッチ）と、Stormbreaker の並列実行ファブリックおよび追記専用の実行ジャーナルの組み合わせ。 |
| **メモリ管理（MMU）** | 二重境界で統制されたメモリ: ローカルプロジェクトメモリはマシン上に隔離されたまま維持され、恒久メモリへの昇格はローカルの Memory Curator によってゲートされます。 |
| **仮想ファイルシステム** | Production Ontology Runtime: ローカルファーストのソース取り込み、CJK トライグラム FTS5 検索、ハイブリッド Reciprocal Rank Fusion、GraphRAG リトリーバル。 |
| **プロセス間呼び出し（IPC）** | A2A Agent Card Boundary（暗号学的なインポート/エクスポートと呼び出し元ゲーティング）+ Model Context Protocol（MCP）ツール登録。 |
| **パッケージマネージャー** | Agentlas Hub & Cloud: 品質ゲートを内蔵した、エージェントのコンパイル・公開・バージョン管理・共有。 |
| **シェルインターフェース** | 外部クライアントランタイムでは小さく統一されたコマンドセット、ネイティブ Agentlas シェルでは平易な自然言語によるインテントルーティング。 |
| **プロセス初期化** | Briefing Interview Gate を統合した Meta-Agent Factory — コードをコンパイルする前に、エージェントのパラメーターを仕様化します。 |

<p align="center">
  <img src="assets/agentlas-meta-agent-architecture.svg" alt="Figure 1. Agentlas Meta-Agent architecture decomposition">
</p>

<p align="center">
  <sub>図 1. リクエストシェイピング、3 つのビルダー、生成されるパッケージコントラクト、メモリキュレーション、スキルライフサイクル、ランタイムアダプター、同期境界。</sub>
</p>

---

## v1.1.0 の新機能 — Briefing Interview Engine

曖昧な一文プロンプトから生成されたエージェントは、実世界のエッジケースで破綻します。Hephaestus v1.1.0 は、**Briefing Interview Engine** によってタスクの仕様化を OS の第一級サービスとして位置づけます:

*   **定量的な曖昧さゲート:** コンパイルスケジューラーは、プロンプトの明確さを 4 つの主要ベクトル（Goal、Constraints、Scope、Context）で評価します。曖昧さスコアが数値しきい値（ambiguity score $\le 0.2$、各次元ごとの安全下限付き）を満たすまで、ビルドプロセスは厳密にゲートされます。明確なプロンプトは、些細なタスクの質問数に上限を設けるバジェットシステムによって、インタビューループを完全にバイパスします。
*   **レンズ駆動のシステム分析:** 明確化のための質問は、構造化されたレンズテーブル（Scope、Intent、Challenge、System Architecture）から動的に選定され、重要なルーティング指標 — *アンチスコープ境界*（エージェントがやってはいけないこと）、*検証可能な受け入れ基準*、*終了条件* — に焦点を当てます。
*   **Work Brief:** 解決された詳細は `.agentlas/work-brief.json` に凍結され、検証済みのゴール、具体的な制約、ソースタグ付きの仮定台帳、そしてメタデータとしての曖昧さスコアが記録されます。
*   **実行中のコンテキストブリーフ:** CLI ツール `cards migrate` は、ブリーフの詳細をエージェントのルーティングカード上のトリガーとアンチトリガーへ自動的に直接マッピングします。`route --brief` を実行すると、このブリーフがすべての Stormbreaker 実行パケットに伝播し、ライフサイクル全体を通じて制約と終了条件が並列サブプロセスを統制します。
*   **強化されたルーティング判別:** ルーティングカード上のインタビュー検証済みアンチトリガーと、ルーター内部での低信頼度 LLM 再ランキングエスカレーションという両面ゲーティングにより、同一トピック・異なるインテントの衝突（例: セキュリティエージェントがデプロイ用プロンプトを横取りする）を防ぎます。

---

## すべてのインストール方法

### 手動 LLM Adapter インストール

現在の LLM が自分で setup を実行できない場合だけ使ってください。共有 Hephaestus
runner と、対応 LLM tools 向けの command adapters をインストールします。

```bash
xcode-select --install   # Command line tools (skip if already installed)
git --version            # Confirm git is available
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
これにより、ニュートラルランナーが `~/.agentlas/runtime/current/bin/hephaestus` にインストールされ、Claude Code、Codex、Gemini CLI、Antigravity、Cursor 用のコマンドアダプターが登録されます。インストーラーは、登録後に各ランタイムサーフェスを検証します。

### ランタイム別プラグインドライバー

<details>
<summary>Claude Code プラグイン</summary>

OS のターミナルから:
```bash
claude plugin marketplace add https://github.com/agentlas-ai/Agentlas-OS --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```
*注: Claude Code はエイリアスとして `claude plugins ...` もサポートしていますが、この README では一貫性のため単数形の `claude plugin ...` を使用します。*

</details>

<details>
<summary>Codex プラグイン</summary>

OS のターミナルから:
```bash
codex plugin marketplace add agentlas-ai/Agentlas-OS --ref v1.1.44
codex plugin add hephaestus@agentlas-core-engine
```
*注: Codex アプリ内では `/plugin marketplace add` は利用できません。上記の 2 つのコマンドを OS のターミナルで実行してください。OS ターミナルの CLI コマンドは単数形（`codex plugin`）ですが、Codex アプリ内のプラグインブラウザーのスラッシュコマンドは複数形（`/plugins`）です。インストール後は、`/prompts:hep-build` がアプリ内のエントリーポイントになります。*

</details>

<details>
<summary>プロジェクトにファイルをコピー（手動ドライバー）</summary>

リポジトリをクローンし、`AGENTS.md`、`agent.md`、`agents/`、`skills/`、`modes/`、`schemas/`、`templates/`、`.agentlas/` をワークスペースにコピーします。ランタイムフォルダー（`.claude/`、`codex/`、`.gemini/`、`.agents/`）は、同一の正準コアに対するアダプターとして機能します。

</details>

**話しかけるだけ:** インストール後は、ネイティブ Agentlas インターフェース内で平易な自然言語で話しかければ、タスクは自動的にルーティングされます。外部 LLM tools では、以下に示す明示的なコマンドを使用してください。どのようなエージェントが存在するのか分からないときは、まず `/hep-search` から始めてください。Telegram を接続するには、Claude Code では `/hep-connect`、Codex では `/prompts:hep-connect` を使います。

---

## コマンドサーフェス

ネイティブ Agentlas 環境内では、Hephaestus はコマンドレスで動作します。外部 LLM tools では、意図的に小さく保たれた可視コマンドセットを使用します。Stormbreaker、リサーチロードアウト、設定テーブルといったシステムレベルのユーティリティは、コンテキストから自動的にアタッチされます:

| システムサブシステム | シェルコマンド | 例 |
| :--- | :--- | :--- |
| **プロセスビルダー** | `/hep-build` | `/hep-build create a customer support agent for Shopify refunds` |
| **A2A スケジューラー** | `/hep-network` | `/hep-network split this launch plan into research, copy, QA, and release agents` |
| **クラウド状態同期** | `/hep-cloud` | `/hep-cloud use my saved finance analyst agent to review this report` |
| **ディレクトリ検索** | `/hep-search` | `/hep-search find agents for a market report workflow` |
| **プロセス間呼び出し（IPC）** | `/hep-call` | `/hep-call market-researcher, report-writer {draft a market report}` |
| **パッケージエクスポーター** | `/hep-upload` | `/hep-upload ./agents/customer-support-hq` |
| **Telegram 設定** | `/hep-connect` または `/prompts:hep-connect` | `/hep-connect Telegram for Marketing Agent Team` |

---

## OS サブシステム

### Meta-Agent Factory — プロセス生成
3 つのビルダーを用いる統合コンパイルファクトリーです。生成されるすべてのパッケージはグローバルコマンド（`.agentlas/global-commands.json`）を登録し、検証スクリプトを同梱します — コンパイル済みパッケージの実行方法をユーザーが推測する必要は一切ありません:

| コンパイルモード | ルーティング先 | 出力アーティファクト |
| :--- | :--- | :--- |
| **シングルエージェント** | `10-single-agent-builder` | ローカライズされたスキル、メモリコントラクト、ランタイムアダプターを備えたスタンドアロンワーカー。 |
| **マルチエージェントチーム** | `20-multi-agent-team-builder` | PM Orchestrator、Memory Curator、Policy Gate、QA、検証スクリプトを含む階層型チーム。 |
| **ワークスペースパッケージャー** | `30-agentlas-packager` | ランタイムへのインポート、CLI 実行、GitHub 配布に対応したコンパイル済みバンドル。 |

*Briefing Interview Gate:* ビルダーは **briefing interview gate**（[docs/builder-interview-research-gate.md](docs/builder-interview-research-gate.md)）を用いてプロセスを開始します: レンズ駆動の質問を行い、曖昧さのしきい値を評価し、一次情報源を検索し、Work Brief を出力します。

---

### Network 2.0 — スケジューラー

<p align="center">
  <img src="assets/hephaestus-network-architecture.svg" alt="Figure 2. Hephaestus Network 2.0 A2A networking architecture">
</p>

<sub>図 2. A2A スケジューリング: LLM ランタイム、ローカルファーストのオーケストレーター、ルーティングカード、ローカルメモリ、そして Agentlas Hub の A2A/MCP フォールバック。</sub>

*   **Routing Cards:** すべてのエージェント、チーム、プラグインは、トリガー、アンチトリガー、能力、リスクプロファイル、メモリパラメーターを含む標準化されたカードを同梱します。検証に失敗したカードはルーティングから除外されます。
*   **ローカルファーストディスパッチ:** ディスパッチはまずローカルで解決されます（プロジェクトオーバーライド $\rightarrow$ ローカルカード）。Agentlas Hub への外部ルックアップはキーワードにまでレダクションされ、生のプロンプトがローカル環境の外へ出ることはありません。
*   **一時的なタスクフォース:** 複合的なリクエストは Hub/ローカルのタスクフォース計画へ分解され、Stormbreaker エンベロープ、セッションヒント、オントロジーパスウェイをパッキングします。名前付きスペシャリストが動的にスケジュールされ、一時的なオーケストレーターがタスクのハンドオフを管理します。
*   **レシート駆動の実行:** すべてのルーティング決定はレシートを書き出します。ルーターが決定するのはどのエージェントまたはパッケージを呼び出すかのみであり、ツール実行権限は厳密にサンドボックス化されたまま、アクティブなランタイムが管理します。
*   **バイリンガルベンチマーク:** 自動ルーティングは、トップ 3 リコール $\ge 90\%$ かつプライバシーリークゼロを要求するバイリンガル（韓国語 + 英語）ベンチマークによってゲートされます。低信頼度のパスは、ランタイムレベルの Router Agent 再ランキングへエスカレーションされます。

詳細: [docs/hephaestus-network-2.0.md](docs/hephaestus-network-2.0.md) · ランタイムサポートマトリクス: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)

---

### Stormbreaker — 規律ある実行
Stormbreaker は、エージェント OS の実行ゲーティングサブシステムです。すべての成果が決定的チェックによって検証されるまで、エージェントが成功を報告したり終了したりしないことを保証します:

```text
Kernel Gating Envelope:
[Scope Lock] -> [Decomposition] -> [Parallel Work Packets] -> [Verify Contracts] -> [Bounded Repair] -> [Final Gate]
```

ローカルの実行ジャーナルにより、長時間の実行は中断後も再開可能です。実行パケットは Work Brief を携行するため、アンチスコープルールと終了基準がすべての並列サブプロセスを統制します。Stormbreaker は明示的な完了状態（**verified / unverified / blocked**）を報告し、自律実行における「完了の演出」を防ぎます。

実行プロトコル: [docs/robustness-protocol.md](docs/robustness-protocol.md) · ベンチマークと評価: [docs/robustness-eval.md](docs/robustness-eval.md)

---

### Ontology Runtime — 知識ファイルシステム
知識集約型の運用のために、`bin/ontology` はセマンティックファイルシステムとして機能し、非構造化のローカルファイルをエージェントが読み取れるデータベーススタックへ変換します:

```text
Ingested Files -> [Parser Adapter] -> [CJK trigram/bigram tokenization] 
  -> [FTS5 + SQLite Storage] -> [Reciprocal Rank Fusion Ranking] -> [GraphRAG Search]
```

GPL 依存ゼロのファーストパーティ韓国語ドキュメントパース（HWPX およびレガシー HWP5）を備えています。完全にローカルかつ SQLite ベースで動作し、機密・プライベートなチャンクは隔離され、外部クラウドフックに到達することを防ぎます。

```bash
bin/ontology ingest ./corpus --scope internal
bin/ontology query "Project Helios Memory Curator" --agent verifier
bin/ontology memory candidates
```

詳細: [docs/ontology-runtime.md](docs/ontology-runtime.md)

---

### 統制されたメモリ — キュレーションによる昇格
*   **ローカルプロジェクトメモリ:** `~/.agentlas/networking/` 以下に保存され、ローカルマシンに隔離されます。明示的な承認なしにエクスポートすることはできません。
*   **ワークスペースパーソナライゼーション:** 借用した Cloud/Hub エージェントのパーソナライゼーションログ（サマリー、プレイブック、プラグインロック、レシート）を、生のプロンプト・認証情報の値・プライベートファイルを保存することなく管理します。
*   **キュレーターゲーティング:** スキルとメモリの変更は、候補として保持されます。ローカルのキュレーターがホールドアウト/リプレイの証明、ロールバックのカバレッジ、セキュリティポリシーの承認を確認して初めて、恒久ステータスへ昇格します。

---

### A2A Boundary — エージェント間分離
標準化された CLI コマンドにより、安全なエージェント間連携が可能です:

```bash
agentlas-cloud ao a2a import ./agent-card.json .
agentlas-cloud ao a2a export . --agent local/10-builder
agentlas-cloud route "run the release check" --caller local/orchestrator .
```
インポートは提案として扱われ（自動呼び出しを制限）、エクスポートはプライベートなパスとロジックをレダクションし、呼び出しはルーティング解決の前に呼び出し元ゲーティングを通過します。

---

## エンタープライズのための設計

エンタープライズに必要なのは、孤立した Python エージェントを書くためのもう 1 つの方法ではありません。必要なのは、それらを**統制されたワークフォースとして運用する**ことです。Hephaestus は、まさにこの運用モデルのために設計されています:

*   **調達レバレッジとしてのモデル中立性:** エージェント、メモリリポジトリ、知識ドメインは、あなたの管理下にあるローカル資産として保存されます。新しいモデルプロバイダーへの移行（あるいは Ollama や Llama のようなローカルモデル、DeepSeek・GLM・Gemini・Claude のようなエンタープライズエンジンの活用）は、コードベースの移行ではなく、単なる設定の更新です。
*   **構造としての監査可能性:** すべてのルーティング決定、実行ステップ、メモリ候補、キュレーター決定はテキストファイルとして記録されます。diff・監査・コミットが可能です。作業は検証済みであるか、未検証としてフラグ付けされるかのいずれかです。
*   **決定的なパイプラインゲート:** セキュリティフィルター、アンチスコープ、ルーティングカードのトリガー、プロンプトのサニタイズは OS パイプラインにハードコードされており、LLM のシステム指示やガイドラインには依存しません。
*   **生成前の仕様化:** Briefing Interview Engine はリクエストの曖昧さを測定し、そのスコアを Work Brief に刻印します。これにより、タスクの実行は常に「合意された内容」まで遡って監査できます。
*   **ローカルファーストのデータ境界:** 生のテキスト、ドキュメント、データベースファイルはローカルに留まります。外部とのトランザクションはレダクションされ、オプトインです。

### フレームワークの位置づけ
CrewAI、LangChain、ベンダー製エージェント SDK は**ライブラリ**として機能します — 単一プロセス内でカスタムエージェントロジックを書くには優れた選択肢です。Hephaestus は**ランタイム基盤**として動作します: ワークスペースランタイムをまたいでエージェントを仕様化し、パッケージ化し、ルーティングし、実行し、監査し、移行します。フレームワークのコードは Hephaestus パッケージの内部で動作し、カーネルが要求するのは、エージェントがディレクトリコントラクトと Routing Card を守ることだけです。

---

## 生成される成果物（プロセスパッケージング）

Hephaestus は、任意のワークスペースランタイムがパース・インストール・検証・実行できる標準ディレクトリレイアウトへエージェントをパッケージします:

```text
├── AGENTS.md                          # Canonical route configurations
├── agent.md / agents/                 # Single worker or team roles
├── skills/                            # Local agent skills and capabilities
├── modes/                             # Custom agent execution modes
├── schemas/                           # Validation contracts and schemas
├── templates/                         # Configuration templates
├── .agentlas/                         # System Directory: routing cards, work briefs,
│                                      # global commands, memory contracts, eval plans
├── .claude/ codex/ .gemini/ .agents/  # Runtime shims (driver adapters over the core)
├── scripts/
│   ├── verify-package.sh              # Package structure verifier
│   └── public_safety_check.sh         # Secret and credentials scanner
└── docs/                              # Briefing records, tool specifications,
                                       # and prompt contracts
```

---

## 目的別ドキュメント

| システム上の目的 | 参照ドキュメント |
|---|---|
| 正準ルートを理解する | [`AGENTS.md`](AGENTS.md) |
| チームコントラクト全体を見る | [`agent.md`](agent.md) |
| アーキテクチャの一次情報源 | [`docs/source-of-truth.md`](docs/source-of-truth.md) |
| ランタイム境界 | [`docs/runtime-sync-boundaries.md`](docs/runtime-sync-boundaries.md) |
| ブリーフィングインタビューとリサーチゲート | [`docs/builder-interview-research-gate.md`](docs/builder-interview-research-gate.md) |
| Network 2.0 ルーティング | [`docs/hephaestus-network-2.0.md`](docs/hephaestus-network-2.0.md) |
| Stormbreaker プロトコル | [`docs/robustness-protocol.md`](docs/robustness-protocol.md) |
| 正準 Goal + UltraCode ハーネス | [`docs/stormbreaker-goal-ultracode-harness.md`](docs/stormbreaker-goal-ultracode-harness.md) |
| Ontology ランタイム | [`docs/ontology-runtime.md`](docs/ontology-runtime.md) |
| メモリアーキテクチャ | [`docs/memory-architecture.md`](docs/memory-architecture.md) |
| Experience と Taste アセット | [`docs/agent-experience-assets.md`](docs/agent-experience-assets.md) |
| MCP ビルド解決 | [`docs/mcp-build-resolution.md`](docs/mcp-build-resolution.md) |
| モデル割り当て | [`docs/model-allocation.md`](docs/model-allocation.md) |
| スキルライフサイクルの昇格 | [`docs/skill-lifecycle-promotion.md`](docs/skill-lifecycle-promotion.md) |
| Cloud ランタイムバンドル | [`docs/agentlas-cloud-runtime.md`](docs/agentlas-cloud-runtime.md) |
| パッケージの検証 | [`scripts/verify-package.sh`](scripts/verify-package.sh) |
| 公開セーフティチェック | [`scripts/public_safety_check.sh`](scripts/public_safety_check.sh) |

---

## 公開セーフティ境界

このリポジトリには、Agentlas の課金/アカウントロジック、本番クラウド認証情報、顧客データベース、生のプライベートトランスクリプト、ネイティブのキーチェーンマネージャー、プライベートなデプロイスクリプトは**含まれていません**。

Hephaestus がコンパイルする公開向けの出力パッケージは、ローカルの絶対パス、API キー、サービスアカウントキー、`.env` シークレット、生のトランスクリプト、顧客ログ、開発者のプライベートノートを除外しなければなりません。

---

## コントリビューションと検証

プルリクエストを開く前、または更新を公開する前に、検証テストスイートを実行してください:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/verify-experience-assets-contract.sh
scripts/public_safety_check.sh
```

---

## ライセンス

Apache-2.0 です。[LICENSE](LICENSE) を参照してください。
