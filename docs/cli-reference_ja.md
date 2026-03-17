# pxq CLI 設定リファレンス

## 概要

このページでは、`pxq` の現在実装されている CLI および設定画面を文書化しています。必要に応じて、隣接する例もこのリファレンスに合わせています。

## コマンドリファレンス

### pxq add

キューに新しいジョブを追加します。

**使用方法:**
```bash
pxq add [OPTIONS] COMMAND
```

**引数:**
- `COMMAND` (必須): 実行するコマンド

**オプション:**

| オプション | 短縮形 | 説明 |
|--------|-------|-------------|
| `--provider` | `-p` | 実行プロバイダー (`local`, `runpod`) |
| `--gpu` | | RunPod 用 GPU タイプ (例: `RTX4090:1`) |
| `--region` | `-r` | RunPod データセンター (例: `EU-RO-1`) |
| `--cpu` | | CPU のみのインスタンスを使用 |
| `--volume` | `-v` | ネットワークボリューム ID |
| `--volume-path` | | ネットワークボリュームのマウントパス (デフォルト: `/volume`) |
| `--secure-cloud` | | コミュニティクラウドの代わりにセキュアクラウドを使用 |
| `--cpu-flavor` | | カンマ区切りの CPU フレーバー (例: `cpu3c,cpu3g`) |
| `--template` | `-t` | RunPod テンプレート ID |
| `--image` | `-i` | RunPod コンテナイメージ (例: `ubuntu:22.04`) |
| `--managed` | | 管理モード - 完了後にポッドを自動停止 |
| `--dir` | `-d` | 作業ディレクトリ |
| `--config` | `-c` | 設定ファイルパス |

**注意:** `--gpu` と `--cpu` は相互に排他的です。

### pxq ls

キュー内のすべてのジョブを一覧表示します。

**使用方法:**
```bash
pxq ls [OPTIONS]
```

**オプション:**

| オプション | 短縮形 | 説明 |
|--------|-------|-------------|
| `--all` | `-a` | ターミナル状態のジョブを含む |

### pxq status

ジョブのステータスを確認します。

**使用方法:**
```bash
pxq status [OPTIONS] [JOB_ID]
```

**引数:**
- `JOB_ID` (オプション): ステータスを確認するジョブ ID。省略時はすべてのジョブを表示します。

**オプション:**

| オプション | 短縮形 | 説明 |
|--------|-------|-------------|
| `--all` | `-a` | 完了したものを含むすべてのジョブを表示 |

### pxq ssh

実行中のジョブのポッドに SSH します。

**使用方法:**
```bash
pxq ssh [OPTIONS] JOB_ID
```

**引数:**
- `JOB_ID` (必須): 接続するジョブ ID

**前提条件:** ジョブは `RUNNING` 状態であり、`pod_id` を持ち、SSH ホストを公開している必要があります。

**オプション:**

| オプション | 短縮形 | 説明 |
|--------|-------|-------------|
| `--help` | | このメッセージを表示して終了 |

### pxq server [COMMAND]

サーバー管理コマンド。

**使用方法:**
```bash
pxq server [OPTIONS] [COMMAND]
```

**コマンド:**
- `start`: pxq サーバーをバックグラウンドで開始
- `stop`: pxq サーバーを停止
- `restart`: pxq サーバーを再起動
- `status`: サーバーのステータスを表示

**オプション:**

| オプション | 短縮形 | 説明 |
|--------|-------|-------------|
| `--port` | `-p` | サーバーを実行するポート |
| `--host` | `-h` | サーバーをバインドするホスト |

### pxq cancel

キュー内のジョブをキャンセルします。

**使用方法:**
```bash
pxq cancel JOB_ID
```

**引数:**
- `JOB_ID` (必須): キャンセルするジョブ ID

**注意:** `QUEUED` ステータスのジョブのみキャンセルできます。

### pxq stop [JOB_ID]

実行中のジョブを停止します。JOB_ID が指定されている場合は、その特定のジョブを直接停止します。指定されていない場合は、単一のジョブのみが `RUNNING` ステータスの場合にそのジョブを停止します。

**使用方法:**
```bash
pxq stop [JOB_ID]
```

**引数:**
- `JOB_ID` (オプション): 停止するジョブ ID。省略時は、単一の実行中のジョブを停止します。

**前提条件:** 正確に 1 つのジョブが `RUNNING` ステータスである必要があります。

**注意:** 実行中のジョブがない場合、または複数のジョブが実行中の場合は、エラーが返されます。RunPod ジョブの場合、停止後にポッドは削除されます。

## 設定ソースと優先順位

設定値は、以下の順序で解決されます（優先度は高い順）:

1. **CLI フラグ** – 明示的なコマンドライン引数 (例: `--provider runpod`)
2. **YAML 設定ファイル** – `--config` で指定された設定ファイルの値
3. **環境変数** – `PXQ_` プレフィックス付き変数
4. **組み込みデフォルト** – `Settings` クラスのハードコードされたデフォルト

値が優先度の高いレベルで指定されていない場合、次のレベルが参照されます。例えば、`--provider` が CLI で指定されていない場合、YAML 設定の値が使用され、設定にない場合は環境変数 `PXQ_PROVIDER` がチェックされ、最後にデフォルト値が使用されます。

> **注意**: CLI フラグは、値が `False` または空であっても優先されます。マージロジックは、CLI 値が `None`（つまりフラグが提供されていない）場合にのみ設定にフォールバックします。

## 環境変数

すべての環境変数は `PXQ_` プレフィックスを使用します。これらは Pydantic Settings を通じてロードされます。

| 変数 | タイプ | デフォルト | 説明 |
|----------|------|---------|-------------|
| `PXQ_RUNPOD_API_KEY` | `str` | `None` | RunPod API キー。`--provider runpod` を使用する際に必須。 |
| `PXQ_MAX_PARALLELISM` | `int` | `4` | 並列ジョブの最大数。 |
| `PXQ_LOG_MAX_SIZE_MB` | `int` | `100` | ジョブごとのログローテーションサイズ制限 (MB)。 |
| `PXQ_PROVISIONING_TIMEOUT_MINUTES` | `int` | `15` | ポッドプロビジョニングのタイムアウト（分）。 |
| `PXQ_SERVER_HOST` | `str` | `"127.0.0.1"` | サーバーバインドホスト。 |
| `PXQ_SERVER_PORT` | `int` | `8765` | サーバーバインドポート。 |
| `PXQ_CORS_ORIGINS` | `list[str]` | `["http://localhost", "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]` | 許可された CORS  Origin のカンマ区切りリスト。 |
| `PXQ_DB_PATH` | `Path` | `~/.pxq/pxq.db` | SQLite データベースファイルへのパス。 |
| `PXQ_RUNPOD_SSH_KEY_PATH` | `Path` | `None` | RunPod SSH 接続用の SSH 秘密キーへのパス。 |

> **注意**: `PXQ_CORS_ORIGINS` のようなリスト値は、環境変数として設定する際にカンマ区切りにする必要があります。

## YAML 設定ファイルキー

YAML 設定ファイルでは、以下のキーがサポートされています。これらは `merge_config_with_cli()` を通じて CLI 引数とマージされます。

| キー | タイプ | 説明 |
|-----|------|-------------|
| `provider` | `str` | ジョブプロバイダー: `local` または `runpod`。 |
| `gpu_type` | `str` | RunPod 用 GPU タイプ (例: `RTX4090:1`)。**注意**: `gpu` も後方互換エイリアスとして受け入れられます (例: `gpu: RTX4090:1`) が、`gpu_type` が標準キーです。 |
| `region` | `str` | ポッド展開用の RunPod リージョン。 |
| `cpu_count` | `int` | 割り当てる CPU コア数。 |
| `volume` | `str` | 永続ストレージ用ボリューム ID。 |
| `volume_path` | `str` | ボリュームのマウントパス (`volume` の設定が必要)。 |
| `secure_cloud` | `bool` | RunPod のセキュアクラウドモードを有効化。 |
| `cpu_flavor_ids` | `list[str]` | インスタンス選択用の CPU フレーバー ID リスト。 |
| `template_id` | `str` | RunPod ポッド設定用テンプレート ID。 |
| `image_name` | `str` | RunPod ポッド用コンテナイメージ (例: `ubuntu:22.04`)。`template_id` と相互排他的。 |
| `env` | `dict[str, str]` | ジョブに渡す環境変数。`{{ RUNPOD_SECRET_* }}` プレースホルダーをサポート。 |
| `managed` | `bool` | 管理モードを有効化 (ジョブ完了後にポッドを自動停止)。 |
| `workdir` | `str` | ジョブ実行用の作業ディレクトリ。相対パスは絶対パスに解決されます。 |

> **警告**: 古い例では廃止されたキーが示されている場合があります。これらは**無効**であり、使用しないでください。

## 例

### まずサーバーを起動

`pxq` コマンドを使用する前に、サーバーを起動します:

```bash
pxq server start [--port PORT] [--host HOST]
```

### ローカルジョブの例

```bash
pxq add "python script.py"
```

### RunPod GPU の例

```bash
pxq add "python train.py" --provider runpod --gpu "RTX4090:1" --managed
```

### YAML 設定の例

```yaml
# config.yaml
provider: runpod
gpu_type: RTX4090:1
managed: true
volume: vol-abc123
env:
  API_KEY: "{{ RUNPOD_SECRET_API_KEY }}"
```

```bash
pxq add "python train.py" --config config.yaml
```

## 既知の制約

- **`--gpu` と `--cpu` は相互排他**: 両方のフラグを同時に指定することはできません。
- **`--image` と `--template` は相互排他**: 両方のフラグを同時に指定することはできません。カスタムイメージまたはテンプレートのどちらかを選択してください。
- **`volume_path` には `volume` が必要**: `volume` も同時に指定されている場合のみ有効です。
- **`status` 出力モード**: `JOB_ID` を指定すると単一のジョブを表示します。省略するとすべてのジョブを表示します。
- **`ssh` には実行中のジョブが必要**: ジョブは `RUNNING` 状態で、`pod_id` を持ち、SSH ホストを公開している必要があります。
- **`workdir` パスの解決**: 相対 `workdir` パスは、現在の作業ディレクトリに基づいて絶対パスに解決されます。
- **廃止キーの警告**: 古いドキュメントまたは例では、廃止されたキーが参照されている場合があります。これらのキーは無視され、使用しないでください。
- **詳細なワークフローについては**: [examples/local/README.md](../examples/local/README.md) および [examples/runpod/README.md](../examples/runpod/README.md) を参照してください。
