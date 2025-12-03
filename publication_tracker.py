# ============================================
#  Aoi Ichikawa Publication Intelligence Tracker (Cloud Run Edition)
# ============================================

import requests
import pandas as pd
import json
import re
import datetime
import time
import urllib.parse
import pytz
import os
import sys
from bs4 import BeautifulSoup
from textblob import TextBlob
from langdetect import detect
from googletrans import Translator
import plotly.graph_objects as go
from tqdm import tqdm
from googlesearch import search
from tabulate import tabulate
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ============================================
#  ENVIRONMENT VARIABLES
# ============================================

# GitHub ActionsやColabでのハードコーディングをやめ、環境変数から取得します
# Cloud Runの設定画面でこの値を入力することになります
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

if not SLACK_BOT_TOKEN:
    print("⚠️ Warning: SLACK_BOT_TOKEN is not set. Slack notifications will fail.")

# User's Paper DOIs (変更なし)
DOIs = [
    {
        "doi": "10.31224/5289", 
        "title": "Masami Systems: A Structurally Constrained, Emotionally Persistent AI Companion for Simulating Human-like Connection", 
        "platform": "engrXiv"
    },
    {
        "doi": "10.31224/5381", 
        "title": "A Japanese Persona Is All You Need: A Case Study on AI's Creative Agency Driving the Translation Asymmetry Trap", 
        "platform": "engrXiv"
    },
    {
        "doi": "10.5281/zenodo.17428600", 
        "title": "Technical Letter (ZIP)", 
        "platform": "Zenodo"
    },
    {
        "doi": "10.31224/5745", 
        "title": "Drift of Ungrounded Modality: On Sycophantic Failure in Constitutional AI", 
        "platform": "engrXiv"
    },
    {
        "doi": "10.5281/zenodo.17575634", 
        "title": "In the Lover's Mirror", 
        "platform": "Zenodo"
    },
    {
        "doi": "10.5281/zenodo.17759331", 
        "title": "Anatomy of Conceptual Collapse", 
        "platform": "Zenodo"
    }
]

translator = Translator()
engrxiv_cache = {}

# ---- Slack Diagnostic & Upload Functions ----

def diagnose_and_connect(token, channel_id):
    """
    Diagnoses Slack connection status, Bot identity, and Channel membership.
    """
    print("\n🏥 Slack Connection Diagnosis...")
    if not token:
        print("   ❌ Token is missing.")
        return False

    client = WebClient(token=token)
    
    # 1. Auth Test
    try:
        auth = client.auth_test()
        bot_name = auth['user']
        print(f"   ✅ Authenticated as: {bot_name} (ID: {auth['user_id']})")
    except SlackApiError as e:
        print(f"   ❌ Auth Failed: {e.response['error']}")
        print("      👉 Token is invalid. Please reinstall app and check token.")
        return False

    # 2. Channel Check
    if not channel_id:
        print("   ⚠️ Channel ID is missing. Skipping channel check.")
        return True

    print(f"   🔎 Checking access to channel: {channel_id} ...")
    try:
        info = client.conversations_info(channel=channel_id)
        ch_name = info['channel']['name']
        is_member = info['channel']['is_member']
        
        if is_member:
            print(f"   ✅ Bot is a member of #{ch_name}. Ready to post!")
            return True
        else:
            print(f"   ❌ Bot is NOT a member of #{ch_name}.")
            print(f"      👉 Please go to Slack and type: /invite @{bot_name}")
            return False
            
    except SlackApiError as e:
        error = e.response['error']
        print(f"   ❌ Channel Check Failed: {error}")
        return False

def upload_file_to_slack(token, channel_id, filepath, title):
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return
    
    client = WebClient(token=token)
    try:
        response = client.files_upload_v2(
            channel=channel_id,
            file=filepath,
            title=title
        )
        print(f"✅ Uploaded {title} successfully.")
    except SlackApiError as e:
        print(f"❌ Upload failed for {title}: {e.response['error']}")

# ============================================
#  🚀 DIAGNOSIS START
# ============================================

slack_ready = False
if SLACK_BOT_TOKEN:
    slack_ready = diagnose_and_connect(SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
    if not slack_ready:
        print("\n⚠️ Slack setup issue detected. Notifications may fail.")
        print("   (Proceeding with data collection...)\n")
else:
    print("⚪ Slack Token not set. Skipping diagnosis.\n")


# ---- Fetching Logic ----

def prefetch_engrxiv_search_results():
    global engrxiv_cache
    search_url = "https://engrxiv.org/search/search?query=Aoi+Ichikawa"
    print(f"🔎 Prefetching engrXiv Search Results from: {search_url} ...")
    
    # 疑似的なUser-Agentを設定してブロック回避を試みる
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        s = requests.Session()
        r = s.get(search_url, headers=headers, timeout=15)
        
        if r.status_code != 200:
            print(f"   ❌ Search Page Error: HTTP {r.status_code}")
            return

        soup = BeautifulSoup(r.content, 'html.parser')
        details_divs = soup.find_all('div', class_='details')
        
        count_found = 0
        for det in details_divs:
            text = det.get_text(strip=True)
            match = re.search(r"Downloads:\s*(\d+)", text)
            if not match: continue
            
            dl_count = int(match.group(1))
            
            meta_div = det.find_parent('div', class_='meta')
            title_elem = None
            if meta_div:
                title_elem = meta_div.find_previous_sibling('h3', class_='title')
            
            if not title_elem:
                container = det.find_parent('li') or det.find_parent('div', class_='search-result')
                if container:
                    title_elem = container.find('h3', class_='title') or container.find('a', class_='title')

            if title_elem:
                full_title = title_elem.get_text(strip=True)
                full_title = full_title.replace("Preprint / Version 1", "").strip()
                engrxiv_cache[full_title] = dl_count
                count_found += 1

        print(f"   📊 Cached {count_found} papers from engrXiv search.")

    except Exception as e:
        print(f"   ⚠️ Prefetch Error: {e}")

# Call prefetch immediately
prefetch_engrxiv_search_results()

def get_zenodo_stats(doi):
    api_url = f"https://zenodo.org/api/records?q=doi:\"{doi}\""
    try:
        r = requests.get(api_url, timeout=10)
        data = r.json()
        if data['hits']['total'] > 0:
            stats = data['hits']['hits'][0]['stats']
            return stats.get('unique_views', 0), stats.get('unique_downloads', 0)
        return None, None
    except: return None, None

def get_engrxiv_stats_from_cache(target_title):
    global engrxiv_cache
    if not engrxiv_cache: return None, 0
    t_target = target_title.lower().strip()
    
    for cached_title, downloads in engrxiv_cache.items():
        t_cached = cached_title.lower().strip()
        if t_target in t_cached or t_cached in t_target:
            if len(t_cached) > 10: return None, downloads
    
    t_target_base = t_target.split(":")[0].strip()
    for cached_title, downloads in engrxiv_cache.items():
        t_cached_base = cached_title.lower().split(":")[0].strip()
        if t_target_base == t_cached_base and len(t_target_base) > 5:
             return None, downloads
    return None, 0

def get_altmetric_data(doi):
    try:
        url = f"https://api.altmetric.com/v1/doi/{doi}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "score": data.get("score", 0),
                "cited_by_posts_count": data.get("cited_by_posts_count", 0),
                "cited_by_tweeters_count": data.get("cited_by_tweeters_count", 0),
                "details_url": data.get("details_url")
            }
        return {"score": 0}
    except: return {"score": 0}

def get_hacker_news_details(title):
    search_query = title.split(":")[0].strip()
    api_url = f"http://hn.algolia.com/api/v1/search?query=\"{urllib.parse.quote(search_query)}\"&tags=story"
    comments_preview = []
    try:
        r = requests.get(api_url, timeout=5)
        if r.status_code == 200:
            hits = r.json().get('hits', [])
            if hits:
                best_hit = hits[0]
                story_id = best_hit.get('objectID')
                
                comments_url = f"http://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&hitsPerPage=3"
                c_r = requests.get(comments_url, timeout=5)
                
                if c_r.status_code == 200:
                    c_hits = c_r.json().get('hits', [])
                    for c in c_hits:
                        text = c.get('comment_text', '')
                        clean_text = re.sub('<[^<]+?>', '', text)
                        clean_text = clean_text[:150] + "..." if len(clean_text) > 150 else clean_text
                        comments_preview.append({
                            "author": c.get('author'),
                            "text": clean_text
                        })

                return {
                    "points": best_hit.get('points', 0),
                    "comments_count": best_hit.get('num_comments', 0),
                    "objectID": story_id,
                    "title": best_hit.get('title'),
                    "comments_preview": comments_preview
                }
    except: pass
    return None

def get_researchgate_rough(title):
    query = f"site:researchgate.net {title}"
    try:
        results = search(query, num_results=2, advanced=True)
        for res in results:
            desc = res.description
            reads_match = re.search(r"(\d+)\s*Reads", desc)
            if reads_match: return int(reads_match.group(1))
    except: pass
    return "Protected"

def analyze_sentiment(text):
    if not text: return "N/A"
    try:
        blob = TextBlob(text)
        pol = blob.sentiment.polarity
        return "Positive" if pol > 0.1 else "Negative" if pol < -0.1 else "Neutral"
    except: return "N/A"

# ---- Reporting Functions ----

def generate_markdown_report(records, date_label):
    md = f"# Social Comment Analysis Report\n"
    md += f"**Generated:** {date_label}\n\n"
    md += "## Impact Overview\n"
    
    table_rows = []
    social_highlights = []
    
    for r in records:
        title_main = r['Title'].split(":")[0]
        short_title = title_main[:30] + "..." if len(title_main) > 30 else title_main
        
        am = r['Altmetric']
        hn = r['HackerNews']
        
        hn_pts = hn['points'] if hn else "-"
        hn_cmts = hn['comments_count'] if hn else "-"
        
        # DL Rate Display Logic
        dl_rate_display = r['DL Rate']
        if r['Platform'] != 'Zenodo':
            dl_rate_display = "N/A"
        
        table_rows.append([
            short_title,
            r['Downloads'],
            dl_rate_display,
            am.get('score', 0),
            hn_pts,
            hn_cmts
        ])
        
        if am.get('score', 0) > 0 or (hn and hn['points'] > 0):
            social_highlights.append({"title": r['Title'], "am": am, "hn": hn})

    # Use tabulate for pretty table
    headers = ["Title", "Downloads", "DL Rate", "Altmetric", "HN Pts", "HN Cmts"]
    md += tabulate(table_rows, headers=headers, tablefmt="github", colalign=("left", "right", "right", "right", "right", "right"))
    md += "\n\n"

    md += "## Social Signals & Sentiment\n"
    
    if not social_highlights:
        md += "_No significant social signals detected yet._\n"
    else:
        for item in social_highlights:
            md += f"### {item['title']}\n"
            if item['am']['score'] > 0:
                md += f"**[Altmetric] Score: {item['am']['score']}**\n"
                md += f"- Mentions: {item['am'].get('cited_by_posts_count', 0)}\n"
                if item['am'].get('cited_by_tweeters_count'):
                    safe_title = urllib.parse.quote(item['title'].split(":")[0])
                    md += f"> [Search Tweets](https://twitter.com/search?q={safe_title}&src=typed_query)\n"
                md += f"- [View Details]({item['am'].get('details_url', '#')})\n"
            
            if item['hn']:
                md += f"**[Hacker News] {item['hn']['points']} pts**\n"
                md += f"- [Thread](https://news.ycombinator.com/item?id={item['hn']['objectID']})\n"
                if item['hn']['comments_preview']:
                    for c in item['hn']['comments_preview']:
                        senti = analyze_sentiment(c['text'])
                        icon = "(+)" if senti == "Positive" else "(-)" if senti == "Negative" else "(=)"
                        md += f"  - {icon} **{c['author']}:** \"{c['text']}\"\n"
            md += "\n---\n"
    return md

# ---- Execution ----

records = []
print("🔍 Starting Deep Scan (Robust Edition v31 - Diagnostic & Full Fix)...")

for item in tqdm(DOIs):
    doi, title, plat = item['doi'], item['title'], item['platform']
    
    views, downloads = None, None
    if plat == "Zenodo":
        views, downloads = get_zenodo_stats(doi)
    elif plat == "engrXiv":
        _, downloads = get_engrxiv_stats_from_cache(title)
        views = "N/A"
    
    am_data = get_altmetric_data(doi)
    hn_data = get_hacker_news_details(title)
    rg_reads = get_researchgate_rough(title)
    
    dl_rate = "-"
    if isinstance(views, int) and isinstance(downloads, int) and views > 0:
        dl_rate = f"{round((downloads / views * 100), 1)}%"
    
    records.append({
        "Title": title, "Platform": plat, "DOI": doi, 
        "Views": views, "Downloads": downloads, "DL Rate": dl_rate, 
        "Altmetric": am_data, "HackerNews": hn_data, "RG Reads": rg_reads
    })
    time.sleep(1.0)

# ---- DataFrame & Stats ----
df = pd.DataFrame(records)
total_dl = pd.to_numeric(df['Downloads'], errors='coerce').fillna(0).sum()
df_for_avg = df[~df['Title'].str.contains("Technical Letter", case=False, na=False)]
avg_dl = pd.to_numeric(df_for_avg['Downloads'], errors='coerce').dropna().mean()

# Cloud Runのタイムゾーン対応
try:
    sv_tz = pytz.timezone('Asia/Tokyo') # 日本時間に変更
except:
    sv_tz = pytz.timezone('UTC')

date_label = datetime.datetime.now(sv_tz).strftime('%Y-%m-%d %H:%M %Z')
stats_text = f"As of: {date_label} | Total: {int(total_dl)} | Avg: {avg_dl:.1f}"

# Save Files
csv_filename = f"aoi_metrics_{datetime.date.today()}.csv"
df.to_csv(csv_filename, index=False)

md_report = generate_markdown_report(records, date_label)
md_filename = f"Social_Comment_Analysis_{datetime.date.today()}.md"
with open(md_filename, "w") as f: f.write(md_report)

print("\n" + "="*50)
print(f"📊 REPORT SUMMARY ({date_label})")
print("="*50)
print(f"Total Downloads: {int(total_dl)}")
print(df[["Title", "Downloads", "DL Rate", "Altmetric"]].to_markdown(index=False))

# ---- Visualization ----
df_plot = df.copy()
df_plot['Downloads'] = pd.to_numeric(df_plot['Downloads'], errors='coerce').fillna(0).astype(int)

df_plot['Bar_Text'] = df_plot.apply(
    lambda row: f"{row['Downloads']}<br>[View: {row['Views']}]" if str(row['Views']).isdigit() else str(row['Downloads']), 
    axis=1
)

def parse_rate_safe(x):
    if isinstance(x, str) and '%' in x:
        try: return float(x.strip('%'))
        except: return None
    return None

df_plot['Rate_Val'] = df_plot['DL Rate'].apply(parse_rate_safe)

fig = go.Figure()
fig.add_trace(go.Bar(x=df_plot['Title'].str[:20]+"...", y=df_plot['Downloads'], name='Downloads', marker_color='#482ff7', text=df_plot['Bar_Text'], textposition='auto'))
fig.add_trace(go.Scatter(x=df_plot['Title'].str[:20]+"...", y=df_plot['Rate_Val'], name='DL Rate (%)', yaxis='y2', line=dict(color='#ff6b6b', width=3), mode='lines+markers', connectgaps=False))

fig.add_annotation(text=f"<b>Stats ({date_label})</b><br>Total DL: {int(total_dl)}<br>Avg DL (excl. Letter): {avg_dl:.1f}", xref="paper", yref="paper", x=1.0, y=0.01, xanchor='right', yanchor='bottom', showarrow=False, bgcolor="rgba(255,255,255,0.9)", bordercolor="#333", borderwidth=1, font=dict(size=14, color="black"), align="right")
fig.update_layout(title='<b>Aoi Ichikawa Publication Impact</b>', xaxis_title='Paper', yaxis_title='Downloads', yaxis2=dict(title='DL Rate (%)', overlaying='y', side='right', range=[0, 100]), template='plotly_white', legend=dict(x=0.01, y=0.99), margin=dict(l=20, r=20, t=50, b=100))

# Save Image
img_filename = f"impact_graph_{datetime.date.today()}.png"
html_filename = f"impact_report_{datetime.date.today()}.html"
fig.write_html(html_filename)
try:
    fig.write_image(img_filename, scale=2)
    print("✅ PNG Graph Generated.")
except Exception as e:
    print(f"⚠️ PNG Generation Failed: {e}")
    img_filename = None

# ---- Slack Upload ----
if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID:
    print("\n📨 Uploading to Slack...")
    
    # 1. Image
    if img_filename:
        upload_file_to_slack(SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, img_filename, f"📊 Impact Graph ({date_label})")
    
    # 2. Markdown Report
    upload_file_to_slack(SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, md_filename, f"📝 Social Report ({date_label})")
    
    # 3. CSV
    upload_file_to_slack(SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, csv_filename, "Raw Data (CSV)")
    
    print("✨ All reports sent!")
else:
    print("⚪ Slack Bot Token or Channel ID not set. Files saved locally.")
