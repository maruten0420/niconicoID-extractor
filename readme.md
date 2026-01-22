niconicoID-extractor

Googleフォームの回答CSVからニコニコ動画・YouTubeの情報を集計し、ランキングを作成するツールです。

使い方

Googleフォームから回答をCSV形式で書き出す。

本ツールにCSVをアップロードする。

列番号（回答者名:B, マイリスト:D, 外部リンク:E）に基づき自動集計されます。

セットアップとデプロイ

1. 必要なファイル

GitHubリポジトリには以下のファイルが必要です。

app.py: アプリ本体

requirements.txt: 依存ライブラリのリスト（各パッケージを改行して記述）

2. Streamlit Cloud へのデプロイ

Streamlit Cloud にログイン。

New app からこのリポジトリを選択。

Main file path を app.py に設定してデプロイ。

技術スタック

Python

Streamlit

yt-dlp (動画情報取得用)

トラブルシューティング

Error during processing dependencies!: requirements.txt の中身が1行ずつに分かれているか確認してください。

取得不可と表示される: 動画が削除されているか、非公開マイリストである可能性があります。
