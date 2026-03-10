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
YT_ID_RE = re.compile(r'(?:v=|\/v\/|embed\/|youtu\.be\/|\/shorts\/)([a-zA-Z0-9_-]{11})')

def format_duration(seconds):
    """秒数を 分:秒 形式に変換"""
    if seconds is None:
        return "[不明]"
    try:
        total_seconds = int(seconds)
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes}:{secs:02d}"
    except:
        return "[不明]"

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
                
                # ニコニコの時間は "MM:SS" 形式で返ってくる
                length_str = thumb.find('length').text if thumb.find('length') is not None else "[不明]"
                
                return {
                    'video_id': video_id,
                    'title': thumb.find('title').text,
                    'uploader': thumb.find('user_nickname').text if thumb.find('user_nickname') is not None else "公式/不明",
                    'upload_date': dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'duration': length_str,
                    'url': f"https://www.nicovideo.jp/watch/{video_id}"
                }
    except Exception:
        pass
    return None

def extract_id_manually(url):
    """URLから強引にIDを抜き出す"""
    nico = NICO_ID_RE.findall(url)
    if nico:
        return nico[0], "Niconico"
    yt = YT_ID_RE.findall(url)
    if yt:
        return yt[0], "YouTube"
    return None, None

def extract_urls_from_text(text):
    """自由記入欄などのテキストから複数のURLやIDを安全に抽出する"""
    if pd.isna(text) or not str(text).strip() or str(text).lower() == 'nan':
        return []
    
    text_str = str(text)
    
    # 文章中のURLを抽出 (http/httpsから始まり、空白や改行や"<>などまで)
    urls = re.findall(r'https?://[^\s<>"]+', text_str)
    
    # URLにはなっていないが、smXXXXなどID単体で書かれている場合の抽出
    nicos = NICO_ID_RE.findall(text_str)
    
    result = []
    # 重複排除しつつ追加
    for url in urls:
        if url not in result:
            result.append(url)
            
    joined_urls = " ".join(result)
    for n_id in nicos:
        if n_id not in joined_urls:
            # URLに含まれていないID単体があれば補完して追加
            result.append(f"https://www.nicovideo.jp/watch/{n_id}")
            
    return result

def get_video_metadata(url):
    """yt-dlpを使用して情報を取得"""
    url_str = str(url).strip()
    
    # そもそもURLっぽくないものはスキップ
    if not url_str.startswith('http') and not NICO_ID_RE.search(url_str):
        return None

    # ニコニコ単体動画チェック
    nico_ids = NICO_ID_RE.findall(url_str)
    if nico_ids and "mylist" not in url_str:
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
            info = ydl.extract_info(url_str, download=False)
            
            if 'entries' in info:
                videos = []
                for entry in info['entries']:
                    if entry:
                        v_id = entry.get('id')
                        # マイリストコメントは entry.get('description') に入ることがある
                        comment = entry.get('description') or ""
                        
                        # ニコニコならAPI優先
                        if v_id and (v_id.startswith('sm') or v_id.startswith('so') or v_id.startswith('nm')):
                            nico_data = get_nico_metadata_api(v_id)
                            if nico_data:
                                nico_data['mylist_comment'] = comment
                                videos.append(nico_data)
                                continue
                        
                        videos.append({
                            'video_id': v_id or entry.get('url'),
                            'title': entry.get('title') or "[タイトル取得不可]",
                            'uploader': entry.get('uploader') or entry.get('channel') or "[投稿者不明]",
                            'upload_date': format_yt_date(entry.get('upload_date')),
                            'duration': format_duration(entry.get('duration')),
                            'mylist_comment': comment,
                            'url': entry.get('url') or url_str
                        })
                return videos
            else:
                return [{
                    'video_id': info.get('id'),
                    'title': info.get('title') or "[タイトル取得不可]",
                    'uploader': info.get('uploader') or info.get('channel') or "[投稿者不明]",
                    'upload_date': format_yt_date(info.get('upload_date')),
                    'duration': format_duration(info.get('duration')),
                    'mylist_comment': "",
                    'url': url_str
                }]
    except Exception:
        v_id, platform = extract_id_manually(url_str)
        if v_id:
            return [{
                'video_id': v_id,
                'title': f"[{platform} 情報取得不可]",
                'uploader': "[取得不可]",
                'upload_date': "[取得不可]",
                'duration': "[不明]",
                'mylist_comment': "",
                'url': url_str
            }]
        return None

def format_yt_date(date_str):
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
    respondent_counts = {} 
    
    progress_text = "動画解析中..."
    progress_bar = st.progress(0, text=progress_text)
    total_rows = len(df)

    for i, row in df.iterrows():
        try:
            # 列名で安全に取得。存在しない場合はインデックスをフォールバックに。
            if '回答者名' in df.columns:
                respondent = str(row['回答者名'])
            else:
                respondent = str(row.iloc[1]) if len(row) > 1 else "匿名"

            if 'マイリストのURL' in df.columns:
                mylist_url = str(row['マイリストのURL'])
            else:
                mylist_url = str(row.iloc[4]) if len(row) > 4 else ""

            if 'マイリストに含める事ができない動画を選出する場合' in df.columns:
                ext_text = str(row['マイリストに含める事ができない動画を選出する場合'])
            else:
                ext_text = str(row.iloc[5]) if len(row) > 5 else ""
                
            if respondent == 'nan' or not respondent: respondent = f"匿名_{i+1}"
        except Exception:
            continue

        if respondent not in respondent_counts:
            respondent_counts[respondent] = 0

        # 文章中からURLをすべて抽出（万が一マイリスト欄に文章が書かれても対応できる）
        urls_to_process = []
        urls_to_process.extend(extract_urls_from_text(mylist_url))
        urls_to_process.extend(extract_urls_from_text(ext_text))
        
        # URLの重複を排除
        urls_to_process = list(dict.fromkeys(urls_to_process))
        
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
                        'duration': v.get('duration', "[不明]"),
                        'comment': v.get('mylist_comment', ""),
                        'respondent': respondent
                    })
                    respondent_counts[respondent] += 1

        progress_bar.progress((i + 1) / total_rows, text=f"{progress_text} ({i+1}/{total_rows}行目)")

    if not all_votes: return None, []

    invalid_respondents = [name for name, count in respondent_counts.items() if count != 10]
    votes_df = pd.DataFrame(all_votes)

    # 集計
    ranking = votes_df.groupby('video_id').agg({
        'title': 'first',
        'upload_date': 'first',
        'uploader': 'first',
        'duration': 'first',
        'respondent': lambda x: sorted(list(set(x))),
        'comment': lambda x: " / ".join(filter(None, set(x))) # コメントを結合
    }).reset_index()

    ranking['得票数'] = ranking['respondent'].apply(len)
    ranking = ranking.sort_values(by=['得票数', 'video_id'], ascending=[False, True])
    ranking['順位(被りなし)'] = range(1, len(ranking) + 1)
    ranking['順位(被りあり)'] = ranking['得票数'].rank(ascending=False, method='min').astype(int)
    
    return ranking, invalid_respondents

# --- UI ---
st.title("📊 動画選出集計・ランキングツール")

uploaded_file = st.file_uploader("回答CSVをアップロード", type=['csv'])

if uploaded_file:
    content = uploaded_file.read()
    try:
        df_input = pd.read_csv(io.BytesIO(content), encoding='utf-8')
    except:
        df_input = pd.read_csv(io.BytesIO(content), encoding='shift-jis')

    st.write(f"📋 読込成功: {len(df_input)} 行の回答")

    if st.button("🚀 ランキングを作成する"):
        try:
            with st.spinner("解析中..."):
                result_df, invalid_respondents = process_data(df_input)
            
            if result_df is not None and not result_df.empty:
                if invalid_respondents:
                    st.warning(f"⚠️ 10作品ではない方: {', '.join(invalid_respondents)}")

                # 表示用整理
                final_output = result_df.copy()
                final_output['選出者一覧'] = final_output['respondent'].apply(lambda x: ", ".join(x))
                
                final_output = final_output[[
                    '順位(被りあり)', '得票数', 'title', 'duration', 'video_id', 'upload_date', 'uploader', '選出者一覧', 'comment'
                ]]
                final_output = final_output.rename(columns={
                    'title': '動画タイトル', 
                    'duration': '再生時間',
                    'video_id': '動画ID', 
                    'upload_date': '投稿日時', 
                    'uploader': '投稿者',
                    'comment': 'マイリスコメント'
                })

                st.success("集計完了！")
                st.subheader("🏆 動画ランキング")
                st.dataframe(final_output, use_container_width=True)
                
                csv_data = final_output.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 CSVをダウンロード",
                    data=csv_data,
                    file_name=f"ranking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime='text/csv'
                )
            else:
                st.error("有効な動画データがありませんでした。")
        except Exception as e:
            st.error(f"エラー: {e}")
