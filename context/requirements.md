# requirements

RunPodにジョブを発行し、ジョブが完了したらインスタンスも停止する。
ジョブを実行したら ファイルをrunpodにアップロードし、指定したコードを実行できる
Pod上での実行ログを定期的に取得し、ダッシュボードから参照できるようにする。Pythonの標準出力などをイメージしています。


- RunPodでの最大並列実行数を指定可能
- `--managed` オプションで、マネージドの実行になる
  - 指定したコマンドの実行が完了したらPodも停止ではなく削除する


## pxq コマンド

pxqコマンドでローカル/RunPodにジョブを投げられる
pueue コマンドのようなコマンドのシンプルさ

コマンド例: 

- pxq add "uv run python experiments/exp001/run.py" --provider runpod --gpu RTX4090:1 --volume 77yhuyo55k
- pxq add "uv run python experiments/exp001/run.py --config exp001.yaml" --provider runpod --gpu RTX4090:1 --volume 77yhuyo55k
- pxq add "uv run python scripts/dataset-download.py" --provider runpod --cpu --volume 77yhuyo55k
- pxq add "uv run python experiments/exp001/run.py" --provider runpod --managed --gpu RTX4090:1 --volume 77yhuyo55k
- pxq add "uv run python run.py" --provider runpod --gpu RTX4090:1 --dir experiments/exp001 
- pxq add "uv run python experiments/exp001/run.py" --provider runpod --gpu RTX4090:1 
- pxq add "uv run python experiments/exp001/run.py" --config exp001.yaml
- pxq ls
- pxq status  (デフォルトではrunning/queue ステータスのジョブ一覧)
- pxq status -a (--all ですべてのステータスのジョブ一覧)
- pxq ssh 0  (0はジョブID)


## ダッシュボード

jobのステータス、実行環境、コマンド、実行時間、ログを確認できる
fastapi, (必要ならpydantic), htmx, tailwindcss

### ダッシュボードコマンド

- pxq server   ダッシュボードを起動
- pxq server --port 8765


## examples

プロジェクトルートにexamples/ ディレクトリを作成する。
それぞれにpxqコマンドを使用する手順を記載したREADME.mdを作成する。

### local

README.mdに手順を記載する。
ローカルでの並列実行ジョブ数を1つまでとし、2つのジョブが順番に実行されるようにする。

### runpod

README.mdに次の2段階の手順を記載する。

1. CPUのPodを起動し、作成済みのRunPodのVolumeに対して、 kaggleから space-titanic のデータセットをダウンロードするマネージドジョブを起動する
2. space-titanicデータセットをダウンロードしたVolumeをマウントして、 RTX4090:1 のPodで pytorchを学習・推論するマネージドジョブを実行する


## その他
- docs/ 配下にCLIのドキュメントを作成する
  - how-to-use.md に使い方を記載
  - how-to-use-ja.md に使い方を日本語で記載
- t-wada 提唱するTDDに従って開発を行う
- 結合テストについて
  - RunPodには `RUNPOD_SECRET_KAGGLE_API_TOKEN` と `RUNPOD_SECRET_KAGGLE_USERNAME` と `RUNPOD_SECRET_KAGGLE_KEY`を定義してあります
  - Kaggleのspace-titanicデータセットを利用し、全体の10%程度のデータを利用してGPUで学習・推論を行ってください。
- runpod_openapi.json に RunPodのAPI全体の仕様書が記載してあります。 
- pythonの実行ではuv を利用すること
- pythonパッケージの追加では、`uv add {パッケージ名}` とすること
- uv tool として pxq コマンドを利用できるようにすること
