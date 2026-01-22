import streamlit as st
import pandas as pd
import re
from datetime import datetime
import time
import yt_dlp
import io

# --- ページ設定 ---
st.set_page_config(page_title="動画選出集計ツール", layout="wide")

# --- 定数・正規表現 ---
# ニコニコ動画のID(sm123...)を抽出する用
NICO_ID_RE = re.compile(r'(sm\d+|so\d+|nm\d+)')

def get_video_metadata(url):
    """yt-dlpを使用して動画またはマイリストの情報を取得する"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,  # マイリストの場合は中身のリストだけ取得（高速化）
        'skip_download': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 情報を抽出
            info = ydl.extract_info(url, download=False)
            
            # マイリスト/プレイリストの場合
            if 'entries' in info:
                videos = []
                for entry in info['entries']:
                    if entry:
                        videos.append({
                            'video_id': entry.get('id') or entry.get('url'),
                            'title': entry.get('title') or "[タイトル取得不可]",
                            'uploader': entry.get('uploader') or entry.get('channel') or "[投稿者不明]",
                            'upload_date': format_date(entry.get('upload_date')),
                            'url': entry.get('url') or f"https://www.nicovideo.jp/watch/{entry.get('id')}"
                        })
                return videos
            
            # 単一動画の場合
            else:
                return [{
                    'video_id': info.get('id'),
                    'title': info.get('title') or "[タイトル取得不可]",
                    'uploader': info.get('uploader') or info.get('channel') or "[投稿者不明]",
                    'upload_date': format_date(info.get('upload_date')),
                    'url': url
                }]
    except Exception as e:
        # 取得に失敗した場合（非対応サイト、削除済み、非公開など）
        return None

def format_date(date_str):
    """YYYYMMDD 形式を YYYY-MM-DD 00:00:00 に変換"""
    if not date_str or not isinstance(date_str, str):
        return "[不明]"
    try:
        dt = datetime.strptime(date_str, '%Y%m%d')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return date_str

def process_data(df):
    """CSV全体をスキャンしてランキングデータを作成"""
    all_votes = []
    video_meta_cache = {} # 動画情報をキャッシュして重複取得を防ぐ
    
    progress_text = "動画情報を解析中..."
    progress_bar = st.progress(0, text=progress_text)
    total_rows = len(df)

    for i, row in df.iterrows():
        # 指定された列からデータを取得
        # B:1, C:2, D:3, E:4 (0-indexed)
        respondent = str(row.iloc[1]) if len(row) > 1 else "匿名"
        mylist_url = str(row.iloc[3]) if len(row) > 3 else ""
        ext_url = str(row.iloc[4]) if len(row) > 4 else ""

        # 対象URLのリストを作成（空文字は除外）
        urls_to_process = [u.strip() for u in [mylist_url, ext_url] if u.strip() and u != 'nan']
        
        for url in urls_to_process:
            # キャッシュにあるか確認（URL単位）
            if url in video_meta_cache:
                results = video_meta_cache[url]
            else:
                results = get_video_metadata(url)
                video_meta_cache[url] = results
                time.sleep(0.1) # サーバー負荷軽減

            if results:
                for v in results:
                    all_votes.append({
                        'video_id': v['video_id'],
                        'title': v['title'],
                        'uploader': v['uploader'],
                        'upload_date': v['upload_date'],
                        'respondent': respondent
                    })
            else:
                # 取得不可の場合
                # URLからIDだけ正規表現で抜けるか試みる
                nico_ids = NICO_ID_RE.findall(url)
                if nico_ids:
                    for n_id in nico_ids:
                        all_votes.append({
                            'video_id': n_id,
                            'title': "[取得不可]",
                            'uploader': "[取得不可]",
                            'upload_date': "[取得不可]",
                            'respondent': respondent
                        })
                else:
                    # 完全に不明な場合
                    all_votes.append({
                        'video_id': url,
                        'title': "[取得不可/非対応]",
                        'uploader': "[取得不可]",
                        'upload_date': "[取得不可]",
                        'respondent': respondent
                    })

        progress_bar.progress((i + 1) / total_rows, text=f"{progress_text} ({i+1}/{total_rows}行目)")

    if not all_votes:
        return None

    # 集計処理
    votes_df = pd.DataFrame(all_votes)
    
    # 動画IDごとにグループ化し、選出者をリストにまとめる
    ranking = votes_df.groupby('video_id').agg({
        'title': 'first',
        'upload_date': 'first',
        'uploader': 'first',
        'respondent': lambda x: sorted(list(set(x))) # 重複排除してソート
    }).reset_index()

    # 選出人数を計算
    ranking['count'] = ranking['respondent'].apply(len)
    
    # ソート（票数降順、ID昇順）
    ranking = ranking.sort_values(by=['count', 'video_id'], ascending=[False, True])
    
    # 順位付け（被りあり/なし）
    ranking['順位(被りなし)'] = range(1, len(ranking) + 1)
    ranking['順位(被りあり)'] = ranking['count'].rank(ascending=False, method='min').astype(int)
    
    return ranking

# --- UI 部分 ---
st.title("📊 動画選出集計・ランキングツール")
st.info("GoogleフォームのCSVを読み込み、マイリスト内動画を含めて自動集計します。")

uploaded_file = st.file_uploader("CSVファイルをアップロード（B:回答者, D:マイリスト, E:外リンク）", type=['csv'])

if uploaded_file:
    # エンコーディングの判定
    content = uploaded_file.read()
    try:
        df_input = pd.read_csv(io.BytesIO(content), encoding='utf-8')
    except:
        df_input = pd.read_csv(io.BytesIO(content), encoding='shift-jis')

    st.write("📋 入力データプレビュー (先頭5件)")
    st.dataframe(df_input.head())

    if st.button("🚀 ランキングを作成する"):
        result_df = process_data(df_input)
        
        if result_df is not None:
            # 列の並び替えと選出者の展開
            max_voters = result_df['count'].max()
            voter_cols = [f"選出者{i+1}" for i in range(max_voters)]
            
            # 選出者リストを個別の列に展開
            voters_expanded = pd.DataFrame(
                result_df['respondent'].tolist(), 
                index=result_df.index
            ).iloc[:, :max_voters]
            voters_expanded.columns = voter_cols[:len(voters_expanded.columns)]

            final_output = pd.concat([
                result_df[['順位(被りなし)', '順位(被りあり)', 'title', 'video_id', 'upload_date', 'uploader']],
                voters_expanded
            ], axis=1)

            final_output = final_output.rename(columns={
                'title': '動画タイトル',
                'video_id': '動画ID',
                'upload_date': '投稿日時',
                'uploader': '投稿者'
            })

            st.success("集計が完了しました！")
            
            # 画面表示
            st.subheader("🏆 集計結果ランキング")
            st.dataframe(final_output)

            # CSVダウンロード
            csv_data = final_output.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 結果をCSVとしてダウンロード",
                data=csv_data,
                file_name=f"ranking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime='text/csv',
            )
        else:
            st.warning("有効な動画データが見つかりませんでした。列の設定やURLを確認してください。")

st.divider()
st.caption("※ニコニコ動画マイリスト・YouTube動画に対応しています。非対応サイトや非公開設定の場合はIDのみ抽出されます。")
