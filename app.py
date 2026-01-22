import streamlit as st
import pandas as pd
import re
from datetime import datetime
import time
import yt_dlp
import io
import requests
import xml.etree.ElementTree as ET

# --- ページ設定 ---
st.set_page_config(page_title="動画選出集計ツール", layout="wide")

# --- 定数・正規表現 ---
NICO_ID_RE = re.compile(r'(sm\d+|so\d+|nm\d+)')

def get_nico_metadata_api(video_id):
    """ニコニコ動画の公式外部API(getthumbinfo)から情報を取得する"""
    api_url = f"https://ext.nicovideo.jp/api/getthumbinfo/{video_id}"
    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            if root.get('status') == 'ok':
                thumb = root.find('thumb')
                raw_date = thumb.find('first_retrieve').text
                dt = datetime.fromisoformat(raw_date)
                return {
                    'video_id': video_id,
                    'title': thumb.find('title').text,
                    'uploader': thumb.find('user_nickname').text if thumb.find('user_nickname') is not None else "公式/不明",
                    'upload_date': dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': f"https://www.nicovideo.jp/watch/{video_id}"
                }
    except Exception:
        pass
    return None

def get_video_metadata(url):
    """yt-dlpを使用して情報を取得し、ニコニコの場合は専用APIで補完する"""
    nico_ids = NICO_ID_RE.findall(url)
    if nico_ids:
        data = get_nico_metadata_api(nico_ids[0])
        if data:
            return [data]

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'entries' in info:
                videos = []
                for entry in info['entries']:
                    if entry:
                        v_id = entry.get('id')
                        if v_id and (v_id.startswith('sm') or v_id.startswith('so') or v_id.startswith('nm')):
                            nico_data = get_nico_metadata_api(v_id)
                            if nico_data:
                                videos.append(nico_data)
                                continue
                        
                        videos.append({
                            'video_id': v_id or entry.get('url'),
                            'title': entry.get('title') or "[タイトル取得不可]",
                            'uploader': entry.get('uploader') or entry.get('channel') or "[投稿者不明]",
                            'upload_date': format_date(entry.get('upload_date')),
                            'url': entry.get('url') or (f"https://www.nicovideo.jp/watch/{v_id}" if v_id else url)
                        })
                return videos
            else:
                return [{
                    'video_id': info.get('id'),
                    'title': info.get('title') or "[タイトル取得不可]",
                    'uploader': info.get('uploader') or info.get('channel') or "[投稿者不明]",
                    'upload_date': format_date(info.get('upload_date')),
                    'url': url
                }]
    except Exception:
        return None

def format_date(date_str):
    """YYYYMMDD 形式を YYYY-MM-DD に変換（主にYouTube用）"""
    if not date_str or not isinstance(date_str, str):
        return "[不明]"
    try:
        if len(date_str) == 8:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.strftime('%Y-%m-%d')
    except:
        pass
    return date_str

def process_data(df):
    """CSV全体をスキャンしてランキングデータを作成"""
    all_votes = []
    video_meta_cache = {} 
    
    progress_text = "動画情報を解析中..."
    progress_bar = st.progress(0, text=progress_text)
    total_rows = len(df)

    for i, row in df.iterrows():
        # 安全に値を取得
        try:
            respondent = str(row.iloc[1]) if len(row) > 1 else "匿名"
            mylist_url = str(row.iloc[3]) if len(row) > 3 else ""
            ext_url = str(row.iloc[4]) if len(row) > 4 else ""
        except Exception:
            continue

        urls_to_process = [u.strip() for u in [mylist_url, ext_url] if u.strip() and str(u).lower() != 'nan']
        
        for url in urls_to_process:
            if url in video_meta_cache:
                results = video_meta_cache[url]
            else:
                results = get_video_metadata(url)
                video_meta_cache[url] = results
                time.sleep(0.05) 

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
                # 取得不可の場合のフォールバック
                nico_ids = NICO_ID_RE.findall(url)
                if nico_ids:
                    for n_id in nico_ids:
                        all_votes.append({
                            'video_id': n_id, 'title': "[取得不可]", 'uploader': "[取得不可]",
                            'upload_date': "[取得不可]", 'respondent': respondent
                        })

        progress_bar.progress((i + 1) / total_rows, text=f"{progress_text} ({i+1}/{total_rows}行目)")

    if not all_votes: return None

    votes_df = pd.DataFrame(all_votes)
    # 集計処理
    ranking = votes_df.groupby('video_id').agg({
        'title': 'first',
        'upload_date': 'first',
        'uploader': 'first',
        'respondent': lambda x: sorted(list(set(x)))
    }).reset_index()

    ranking['count'] = ranking['respondent'].apply(len)
    ranking = ranking.sort_values(by=['count', 'video_id'], ascending=[False, True])
    ranking['順位(被りなし)'] = range(1, len(ranking) + 1)
    ranking['順位(被りあり)'] = ranking['count'].rank(ascending=False, method='min').astype(int)
    
    return ranking

# --- UI ---
st.title("📊 動画選出集計・ランキングツール")
st.markdown("""
- **ニコニコ動画**: 投稿日時（秒まで）を表示します。
- **YouTube**: 投稿日（年月日のみ）を表示します。
""")

uploaded_file = st.file_uploader("CSVファイルをアップロード", type=['csv'])

if uploaded_file:
    content = uploaded_file.read()
    try:
        df_input = pd.read_csv(io.BytesIO(content), encoding='utf-8')
    except:
        df_input = pd.read_csv(io.BytesIO(content), encoding='shift-jis')

    st.write("📋 入力CSVプレビュー (5件)")
    st.dataframe(df_input.head())

    if st.button("🚀 ランキングを作成する"):
        try:
            result_df = process_data(df_input)
            
            if result_df is not None and not result_df.empty:
                # 選出者リストを展開
                voter_lists = result_df['respondent'].tolist()
                max_voters = max([len(v) for v in voter_lists]) if voter_lists else 0
                
                # 選出者データをデータフレーム化
                voters_df = pd.DataFrame(voter_lists, index=result_df.index)
                voters_df.columns = [f"選出者{i+1}" for i in range(voters_df.shape[1])]

                # 最終的な出力を結合
                final_output = pd.concat([
                    result_df[['順位(被りなし)', '順位(被りあり)', 'title', 'video_id', 'upload_date', 'uploader']],
                    voters_df
                ], axis=1)

                final_output = final_output.rename(columns={
                    'title': '動画タイトル', 'video_id': '動画ID', 'upload_date': '投稿日時', 'uploader': '投稿者'
                })

                st.success(f"集計完了: {len(final_output)}件の動画が見つかりました。")
                
                # 画面表示
                st.subheader("🏆 集計結果ランキング")
                st.dataframe(final_output)
                
                # CSVダウンロード
                csv_data = final_output.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(label="📥 CSVダウンロード", data=csv_data, file_name=f"ranking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime='text/csv')
            else:
                st.warning("動画情報が見つかりませんでした。CSVの列（B:回答者, D:マイリスト, E:リンク）が正しいか確認してください。")
        except Exception as e:
            st.error(f"プログラム実行中にエラーが発生しました: {e}")
            st.info("CSVの形式や列の並びが想定と異なっている可能性があります。")
