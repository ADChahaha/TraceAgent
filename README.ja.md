<div align="center">

# TraceAgent

**Evidence-grounded Document QA**

PDF / DOCX を Agent が探索できる文書ツリーへ変換し、すべての回答からワンクリックで原文の該当段落へ戻れるローカル QA ワークスペース。

[中文](README.md) · [クイックスタート](#クイックスタート) · [アーキテクチャ](#アーキテクチャ) · [MIT License](LICENSE)

</div>

![TraceAgent 原文ハイライトと検索ステップ](docs/assets/demo-qa-evidence-review.png)

## 従来の RAG との違い

| 観点 | 一般的なチャンク RAG | TraceAgent |
| --- | --- | --- |
| **検索方式** | 固定チャンク分割と Top-K の一括投入 | Markdown 文書ツリーとベクトル索引を生成し、Agent が `ls` / `grep` / `read` / 意味検索を組み合わせて探索 |
| **引用の確認** | ファイル名やページ番号のみで手動確認が必要 | 番号付き引用のクリックで左側に全文を開き、該当段落へ移動してハイライト |
| **長文の閲覧** | 断片の抜粋やテキストのみの応答 | 分割画面で前後の文脈を保持し、ダークモードでも原文エリアは白背景・黒文字を維持 |
| **過程と制御** | 結論のみをブラックボックスで出力 | 探索ステップは回答上部に折りたたんでいつでも展開でき、途中キャンセル・文書追加・SQLite 復元に対応 |

<table>
  <tr>
    <td width="50%">
      <img src="docs/assets/demo-home-workspace.png" alt="TraceAgent ホーム画面" width="100%" />
      <p align="center">ホーム画面と文書アップロード</p>
    </td>
    <td width="50%">
      <img src="docs/assets/demo-qa-workspace.png" alt="TraceAgent ダークモード" width="100%" />
      <p align="center">ダークモードとファイル管理</p>
    </td>
  </tr>
</table>

## クイックスタート

必要な環境：Python 3.11、pnpm。

```bash
# 1. 環境作成とインストール（Python パッケージ + フロントエンドビルド）
conda create -n agent-gate python=3.11 -y && conda activate agent-gate
./scripts/install.sh

# 2. 設定テンプレートをコピーしてモデル情報を記入
cp config.example.toml config.toml
```

`config.toml` に任意の OpenAI 互換エンドポイントを設定します（`api_transport` は `responses` または `chat_completions`）：

```toml
[model]
base_url = "https://your-model-endpoint/v1"
api_key = "your-api-key"
model = "your-model-name"
api_transport = "responses"
```

全サービスを起動して http://127.0.0.1:3000 を開きます：

```bash
./scripts/start.sh
```

ローカルのオブジェクトストレージ、文書サービス、Agent、バックエンド、フロントエンドが一括起動し、`Ctrl+C` で停止します。

<details>
<summary>主な設定と初回起動の補足（タイトル用モデル・PDF 言語・外部 S3・HF 401）</summary>

- **タイトル生成用モデル**：`config.toml` の `[title_model]` を設定すると、軽量な別モデルでセッションタイトルを非同期生成できます。未設定時は `[model]` を共用します。各項目は同名の環境変数でも上書き可能です。
- **初回起動時の embedding モデル取得**：`document_service` は起動時に Hugging Face から OpenVINO 用 embedding モデルを取得しウォームアップします。ローカルに残った HF token で公開モデルが 401 になる場合は `[huggingface].disable_implicit_token = true` を設定してください。
- **PDF の解析言語**：PDF は MinerU で解析します。言語は `[document_service].mineru_lang` で変更できます。
- **ストレージと DB**：オブジェクトストレージは既定でローカルの `storage/data` に保存されます。既存の MinIO や S3 を使う場合は `[storage].endpoint_url` を指定してください。会話履歴は `backend/backend.sqlite3` に保存されます（単一ユーザーのローカル利用向け・認証なし）。

</details>

## アーキテクチャ

```mermaid
flowchart LR
    UI["Next.js ワークスペース"] <-->|"HTTP / SSE"| Backend["backend (FastAPI + SQLite)"]
    Backend -->|"PrepareResources (gRPC)"| Doc["document_service (MinerU / python-docx / OpenVINO)"]
    Doc -->|"raw / documents.zip / index"| S3["storage (S3 互換)"]
    Backend <-->|"ChatCompletion / GenerateTitle (gRPC)"| Agent["agent (LangGraph)"]
    Agent -->|"必要に応じてツリーと索引を参照"| S3
```

```text
agent_proto/       共有 protobuf / gRPC 契約
storage/           ローカル S3 互換オブジェクトストレージ
shared/            オブジェクトストレージクライアントと config.toml ローダー
document_service/  PDF / DOCX 解析、Markdown ツリーとベクトル索引の構築
agent/             LangGraph ベースの文書 QA・タイトル生成サービス
backend/           セッション管理、SQLite 永続化と SSE ストリーミング
frontend/          Next.js デュアルテーマ閲覧・QA ワークスペース
```

詳細ドキュメント：[ARCHITECTURE.md](ARCHITECTURE.md) · [agent](agent/README.md) · [document_service](document_service/README.md) · [backend](backend/README.md) · [frontend](frontend/docs/DESIGN.md)

## License

[MIT](LICENSE)
