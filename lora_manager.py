import gradio as gr
import os
import re
import shutil
import json
import io
import copy
import requests
import base64
import plotly.express as px
import pandas as pd
from collections import Counter, defaultdict
from PIL import Image

# Import ImageHash
try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

# Import OpenCV pour le Smart Crop
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# Import deep-translator
try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

# ==========================================
# CONFIGURATION & DICTIONNAIRES DE LANGUE
# ==========================================

RECIPES_FILE = "lora_recipes.json"
AI_RECIPES_FILE = "ai_recipes.json"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

# Internal keys for control-flow dropdowns. Decoupled from user-visible labels
# so renaming a label in en.json can't silently change branching behaviour.
# Dropdowns use Gradio's `choices=[(label, key)]` tuple form — the handler
# receives the key, never the label.
LIB_MODE_ADD = "lib_mode_add"
LIB_MODE_REMOVE = "lib_mode_remove"
LIB_MODE_REPLACE = "lib_mode_replace"

STRAT_CLASSIC = "strat_classic"
STRAT_BALANCING = "strat_balancing"
STRAT_PRIORITY = "strat_priority"

BACKEND_OLLAMA = "backend_ollama"
BACKEND_OPENAI = "backend_openai"

MSG = {"FR": {}, "EN": {}}
UI_T = {"FR": {}, "EN": {}}

CONTRADICTIONS_LOGIQUES = [
    ("day", "night"), ("daytime", "night"),
    ("solo", "multiple girls"), ("solo", "multiple boys"),
    ("indoors", "outdoors"), ("outside", "inside"),
    ("1girl", "1boy"), ("monochrome", "colorful")
]

def load_languages():
    for lang in ["FR", "EN"]:
        filepath = f"{lang.lower()}.json"
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                MSG[lang] = data.get("MSG", {})
                UI_T[lang] = data.get("UI_T", {})
        else:
            print(f"⚠️ Fichier de langue '{filepath}' introuvable.")

load_languages()

# ==========================================
# ==========================================
# STYLES & JAVASCRIPT — loaded from ./assets
# ==========================================
# Extracted from inline strings in v4.0.2. The runtime contract is identical;
# editors now get syntax highlighting and diffs are sane.
from pathlib import Path as _Path
_ASSETS_DIR = _Path(__file__).resolve().parent / "assets"
css_code = (_ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
custom_js = (_ASSETS_DIR / "scripts.js").read_text(encoding="utf-8")

# ==========================================
# FONCTIONS LOGIQUES PYTHON & UTILITAIRES
# ==========================================

def get_gallery_items(filtered_dataset, lang): return [(item['img_path'], "") for item in filtered_dataset]

def extract_all_tags(dataset):
    all_tags = set()
    for item in dataset:
        tags = [t.strip() for t in item['caption'].split(',') if t.strip()]
        all_tags.update(tags)
    return "|".join(sorted(list(all_tags)))

def browse_folder():
    # Gradio is a web app — a server-side tkinter dialog is the wrong UX:
    # it pops on the host, not the user's browser, and breaks remote use.
    # Paste the path into the textbox instead. Returning gr.update() preserves
    # whatever the user has already typed.
    gr.Info("Paste the dataset folder path into the textbox (e.g. D:\\my-dataset).")
    return gr.update()

def sort_dataset(dataset, order, lang, msg_no_sel, all_tags_str=""):
    if not dataset: return [], [], [], "", "{}", -1
    if order == "Z-A":
        dataset = sorted(dataset, key=lambda x: x['img_name'], reverse=True)
    else:
        dataset = sorted(dataset, key=lambda x: x['img_name'])
    for idx, item in enumerate(dataset): item['id'] = idx
        
    gal_items = get_gallery_items(dataset, lang)
    success_msg = MSG[lang].get("images_loaded", "{count} images loaded.").format(count=len(dataset))
    gr.Info(success_msg)
    return dataset, dataset, [], success_msg, gal_items, [], msg_no_sel, "{}", all_tags_str or extract_all_tags(dataset), -1

def load_dataset(directory, sort_order, lang):
    msg_no_sel = MSG[lang].get("no_selection", "Aucune sélection active.")
    if not os.path.isdir(directory): 
        return [], [], [], MSG[lang].get("folder_not_found", "Dossier introuvable."), [], [], msg_no_sel, "{}", "", -1
    dataset = []
    valid_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    idx = 0
    for filename in sorted(os.listdir(directory)):
        if filename.lower().endswith(valid_extensions):
            img_path = os.path.join(directory, filename)
            txt_path = os.path.splitext(img_path)[0] + '.txt'
            caption = ""
            if os.path.exists(txt_path):
                with open(txt_path, 'r', encoding='utf-8') as f: caption = f.read().strip()
            else:
                with open(txt_path, 'w', encoding='utf-8') as f: pass
            dataset.append({'id': idx, 'img_name': filename, 'img_path': img_path, 'txt_path': txt_path, 'caption': caption})
            idx += 1
    return sort_dataset(dataset, sort_order, lang, msg_no_sel, extract_all_tags(dataset))

def filter_gallery(dataset, search_text, sort_order, lang):
    if not dataset: return [], [], [], "", "{}", -1
    filtered = dataset
    if search_text:
        filtered = [item for item in dataset if search_text.lower() in item['caption'].lower()]
    if sort_order == "Z-A": filtered = sorted(filtered, key=lambda x: x['img_name'], reverse=True)
    else: filtered = sorted(filtered, key=lambda x: x['img_name'])
    return filtered, get_gallery_items(filtered, lang), [], "", "{}", -1

def get_highlighted_html(caption, tracked_words_str):
    if not caption: return "<div style='padding:10px; background:var(--bg-color); border-radius:5px;'></div>"
    html_caption = caption
    if tracked_words_str:
        tracked_words = [w.split(':')[0].strip() for w in tracked_words_str.split(',') if w.strip()]
        tracked_words = sorted([w for w in tracked_words if w], key=len, reverse=True)
        if tracked_words:
            escaped_words = [re.escape(w) for w in tracked_words]
            pattern = re.compile(r'(?i)\b(' + '|'.join(escaped_words) + r')\b')
            html_caption = pattern.sub(r'<mark style="background-color: #ffcc00; color: #000; font-weight: bold; padding: 2px 4px; border-radius: 4px; box-shadow: 0 0 5px rgba(255, 204, 0, 0.5);">\1</mark>', html_caption)
    return f"<div style='padding:15px; border:1px solid #555; background-color: #222; border-radius:8px; line-height:1.6; font-size:1.1em;'>{html_caption}</div>"

def update_word_count(text, lang):
    if not text: return MSG[lang].get("0_words", "0 words")
    words = len(text.split())
    tokens = int(words * 1.3)
    color = "#ff4444" if tokens > 225 else "#44ff44"
    warning = MSG[lang].get("truncation_risk", "") if tokens > 225 else ""
    return f"<div style='color:{color}; font-weight:bold;'>{words} {MSG[lang].get('word_count','words')} (~{tokens} {MSG[lang].get('token_count','tokens')}){warning}</div>"

def get_updated_viewer_data(filtered_dataset, idx, tracked_words, lang):
    if not filtered_dataset or idx < 0 or idx >= len(filtered_dataset): 
        return "", get_highlighted_html("", tracked_words), update_word_count("", lang)
    item = filtered_dataset[idx]
    return item['caption'], get_highlighted_html(item['caption'], tracked_words), update_word_count(item['caption'], lang)

def update_viewer(filtered_dataset, idx, tracked_words, lang):
    if not filtered_dataset or idx < 0 or idx >= len(filtered_dataset): 
        return None, "", "", MSG[lang].get("0_words", "0 words"), -1, MSG[lang].get("no_img_sel", "No image")
    item = filtered_dataset[idx]
    msg = MSG[lang].get("viewing_img", "Viewing: {name}").format(name=item['img_name'])
    return item['img_path'], get_highlighted_html(item['caption'], tracked_words), item['caption'], update_word_count(item['caption'], lang), idx, msg

def silent_save(dataset, filtered_dataset, idx, new_caption, lang):
    if not filtered_dataset or idx < 0 or idx >= len(filtered_dataset): return
    item_filtered = filtered_dataset[idx]
    if item_filtered['caption'] == new_caption: return 
    real_id = item_filtered['id']
    if os.path.exists(item_filtered['txt_path']) and os.path.getsize(item_filtered['txt_path']) > 0: 
        shutil.copy2(item_filtered['txt_path'], item_filtered['txt_path'] + ".bak")
    item_filtered['caption'] = new_caption
    dataset[real_id]['caption'] = new_caption
    with open(item_filtered['txt_path'], 'w', encoding='utf-8') as f: f.write(new_caption)

def clear_selection(lang): 
    return [], MSG[lang].get("no_sel_all", "Aucune sélection (Le Batch impactera **TOUT** le dataset)."), "{}"

def handle_sync(payload_str, dataset, filtered_dataset, old_idx, old_caption, tracked_words, lang):
    silent_save(dataset, filtered_dataset, old_idx, old_caption, lang)
    try:
        data = json.loads(payload_str)
        sel_js = data.get("selected", [])
        view_idx = int(data.get("viewIndex", 0))
    except:
        sel_js = []; view_idx = 0
    real_ids = [filtered_dataset[i]['id'] for i in sel_js if 0 <= i < len(filtered_dataset)] if filtered_dataset else []
    sel_text = MSG[lang].get("selected_multi", "✅ **{count}** sélectionnée(s)").format(count=len(real_ids)) if real_ids else ""
    img_path, hl_html, cap, wc, c_idx, v_status = update_viewer(filtered_dataset, view_idx, tracked_words, lang)
    return dataset, filtered_dataset, real_ids, sel_text, img_path, hl_html, cap, wc, c_idx, v_status, extract_all_tags(dataset)

def save_all_captions(dataset):
    for item in dataset:
        with open(item['txt_path'], 'w', encoding='utf-8') as f: f.write(item['caption'])

def save_single_caption(dataset, filtered_dataset, idx, new_caption, lang):
    if not filtered_dataset or idx < 0 or idx >= len(filtered_dataset): 
        return dataset, filtered_dataset, MSG[lang].get("error", "Error")
    item_filtered = filtered_dataset[idx]
    real_id = item_filtered['id']
    if os.path.exists(item_filtered['txt_path']) and os.path.getsize(item_filtered['txt_path']) > 0: 
        shutil.copy2(item_filtered['txt_path'], item_filtered['txt_path'] + ".bak")
    item_filtered['caption'] = new_caption
    dataset[real_id]['caption'] = new_caption
    with open(item_filtered['txt_path'], 'w', encoding='utf-8') as f: f.write(new_caption)
    msg_success = MSG[lang].get("saved", "Saved: {name}").format(name=item_filtered['img_name'])
    gr.Info(msg_success)
    return dataset, filtered_dataset, msg_success

def nav_prev(dataset, filtered_dataset, idx, current_caption, tracked_words, lang):
    silent_save(dataset, filtered_dataset, idx, current_caption, lang)
    if not filtered_dataset: return dataset, filtered_dataset, None, "", "", MSG[lang].get("0_words", "0 words"), -1, ""
    new_idx = (idx - 1) % len(filtered_dataset) if idx >= 0 else 0
    res = update_viewer(filtered_dataset, new_idx, tracked_words, lang)
    return (dataset, filtered_dataset) + res

def nav_next(dataset, filtered_dataset, idx, current_caption, tracked_words, lang):
    silent_save(dataset, filtered_dataset, idx, current_caption, lang)
    if not filtered_dataset: return dataset, filtered_dataset, None, "", "", MSG[lang].get("0_words", "0 words"), -1, ""
    new_idx = (idx + 1) % len(filtered_dataset) if idx >= 0 else 0
    res = update_viewer(filtered_dataset, new_idx, tracked_words, lang)
    return (dataset, filtered_dataset) + res

def undo_last_action(dataset, history, current_idx, tracked_words, lang):
    if not history: return dataset, dataset, MSG[lang].get("nothing_to_undo", "Nothing"), "", get_highlighted_html("", tracked_words), update_word_count("", lang)
    dataset = copy.deepcopy(history)
    save_all_captions(dataset)
    gr.Warning(MSG[lang].get("undo_success", "Undone"))
    cap, hl_html, wc = get_updated_viewer_data(dataset, current_idx, tracked_words, lang)
    return dataset, dataset, MSG[lang].get("undo_success", "Undone"), cap, hl_html, wc

def load_recipes():
    if os.path.exists(RECIPES_FILE):
        with open(RECIPES_FILE, 'r') as f: return json.load(f)
    return {"Default": "1girl, solo, looking at viewer"}

def save_recipe(name, words):
    if not name: return gr.update(), "Empty name"
    recipes = load_recipes()
    recipes[name] = words
    with open(RECIPES_FILE, 'w') as f: json.dump(recipes, f)
    gr.Info("✅ Recette sauvegardée avec succès !")
    return gr.update(choices=list(recipes.keys()), value=name), "✅ Saved"

def apply_recipe(name):
    return load_recipes().get(name, "")

# ==========================================
# 📚 NOUVEAU MODULE: BIBLIOTHÈQUE CUSTOM
# ==========================================

def render_lib_html(lib_state, lang):
    if not lib_state:
        empty_msg = MSG.get(lang, MSG["FR"]).get("lib_empty", "Bibliothèque vide... Entrez des mots ci-dessous.")
        return f"<div style='padding:10px; color:#9ca3af; font-style:italic;'>{empty_msg}</div>"
    html = "<div id='custom_library_container' style='display:flex; flex-direction:column; gap:8px; margin-top:10px;'>"
    for idx, item in enumerate(lib_state):
        text = item['text']
        is_sel = item.get('selected', False)
        bg_color = "rgba(249, 115, 22, 0.2)" if is_sel else "#1f2937"
        border_color = "#f97316" if is_sel else "#374151"
        safe_t = text.replace("'", "&#39;").replace('"', '&quot;')
        html += f"""
        <div class='lib-item-custom' data-idx='{idx}' style='border: 2px solid {border_color}; background-color: {bg_color}; padding: 10px 15px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; margin-bottom: 5px;'>
            <span style='color: #fff; font-size: 1.05em; pointer-events: none;'>{safe_t}</span>
            <span class='lib-item-delete' data-idx='{idx}' style='color: #fb923c; font-weight: bold; cursor: pointer; padding: 2px 6px; border-radius:4px; font-size:1.1em; background-color: rgba(251, 146, 60, 0.1);' title='Supprimer'>X</span>
        </div>
        """
    html += "</div>"
    return html

def add_to_lib_html(text, lib_state, lang):
    if not text: return gr.update(), lib_state, ""
    new_lib = copy.deepcopy(lib_state)
    items = [x.strip() for x in re.split(r'[\n;]', text) if x.strip()]
    for item in items:
        if not any(x['text'] == item for x in new_lib) and item.lower() != "none":
            new_lib.append({"text": item, "selected": False})
    return render_lib_html(new_lib, lang), new_lib, ""

def toggle_lib_item(idx_str, lib_state, lang):
    new_lib = copy.deepcopy(lib_state)
    try:
        idx = int(str(idx_str).split('_')[0])
        if 0 <= idx < len(new_lib):
            new_lib[idx]['selected'] = not new_lib[idx].get('selected', False)
    except: pass
    return render_lib_html(new_lib, lang), new_lib

def delete_lib_item(idx_str, lib_state, lang):
    new_lib = copy.deepcopy(lib_state)
    try:
        idx = int(str(idx_str).split('_')[0])
        if 0 <= idx < len(new_lib):
            new_lib.pop(idx)
    except: pass
    return render_lib_html(new_lib, lang), new_lib

def uncheck_all_lib(lib_state, lang):
    new_lib = copy.deepcopy(lib_state)
    for x in new_lib: x['selected'] = False
    return render_lib_html(new_lib, lang), new_lib

def clear_lib(lang):
    return render_lib_html([], lang), []

def batch_library_cb(dataset, lib_state, mode, replace_target, selected_ids, search_text, current_idx, tracked_words, lang):
    history = copy.deepcopy(dataset)
    new_dataset = copy.deepcopy(dataset)
    count = 0
    m = MSG.get(lang, MSG["FR"])

    selected_items = [x['text'] for x in lib_state if x.get('selected', False)]
    target = str(replace_target).strip() if replace_target else ""

    # `mode` is the internal enum key (LIB_MODE_*) from the dropdown's tuple
    # choices — not the displayed label. Renaming labels in en.json can no
    # longer change behaviour here.
    action_mode = mode if mode in (LIB_MODE_ADD, LIB_MODE_REMOVE, LIB_MODE_REPLACE) else LIB_MODE_ADD

    if action_mode == LIB_MODE_ADD and not selected_items:
        gr.Warning(m.get("lib_warn_add", "⚠️ Veuillez cocher au moins un mot !"))
        cap, hl, wc = get_updated_viewer_data(new_dataset, current_idx, tracked_words, lang)
        return new_dataset, new_dataset, history, m.get("text_empty", ""), pd.DataFrame(), cap, hl, wc, gr.update()

    elif action_mode == LIB_MODE_REMOVE and not selected_items and not target:
        gr.Warning(m.get("lib_warn_rem", "⚠️ Entrez une Cible OU cochez un mot !"))
        cap, hl, wc = get_updated_viewer_data(new_dataset, current_idx, tracked_words, lang)
        return new_dataset, new_dataset, history, m.get("text_empty", ""), pd.DataFrame(), cap, hl, wc, gr.update()

    elif action_mode == LIB_MODE_REPLACE and not target:
        gr.Warning(m.get("lib_warn_rep", "⚠️ Spécifiez ce qu'il faut remplacer !"))
        cap, hl, wc = get_updated_viewer_data(new_dataset, current_idx, tracked_words, lang)
        return new_dataset, new_dataset, history, m.get("text_empty", ""), pd.DataFrame(), cap, hl, wc, gr.update()

    for item in new_dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        cap = item['caption']; original_cap = cap

        if action_mode == LIB_MODE_ADD:
            existing_tags = [t.strip().lower() for t in cap.split(',')]
            for lib_item in selected_items:
                if lib_item.lower() not in existing_tags:
                    sep = ", " if cap and not cap.endswith(", ") else ""
                    cap = cap + sep + lib_item
                    existing_tags.append(lib_item.lower())

        elif action_mode == LIB_MODE_REMOVE:
            for lib_item in selected_items:
                cap = re.sub(r'(?i)\b' + re.escape(lib_item) + r'\b,?', '', cap)
            if target:
                cap = re.sub(r'(?i)\b' + re.escape(target) + r'\b,?', '', cap)
            cap = re.sub(r',\s*,', ',', cap).strip(', ')

        elif action_mode == LIB_MODE_REPLACE:
            if target and re.search(r'(?i)\b' + re.escape(target) + r'\b', cap):
                replacement = ", ".join(selected_items)
                pattern = re.compile(r'(?i)\b' + re.escape(target) + r'\b')
                cap = pattern.sub(replacement, cap)

        if cap != original_cap:
            item['caption'] = cap; count += 1

    save_all_captions(new_dataset)
    cible_msg = m.get("target_sel", "(sur {count} ciblées)").format(count=len(selected_ids)) if selected_ids else m.get("target_all", "(sur TOUT le dataset)")
    msg = m.get("lib_batch_success", "✅ Mass Batch appliqué dans {count} images {cible_msg}.").format(count=count, cible_msg=cible_msg)
    gr.Info(msg)
    
    filtered_dataset = [item for item in new_dataset if search_text.lower() in item['caption'].lower()] if search_text else new_dataset
    cap_disp, hl_disp, wc_disp = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    
    changes = []
    for old, new in zip(history, new_dataset):
        if old['caption'] != new['caption']:
            changes.append({"File" if lang=="EN" else "Fichier": old['img_name'], "Avant" if lang=="FR" else "Before": old['caption'], "Après" if lang=="FR" else "After": new['caption']})
            if len(changes) >= 10: break
    if not changes: df_res = pd.DataFrame([{"Message": m.get("no_changes", "Aucun changement.")}])
    else: df_res = pd.DataFrame(changes)
        
    return new_dataset, filtered_dataset, history, msg, df_res, cap_disp, hl_disp, wc_disp, get_gallery_items(filtered_dataset, lang)

# === TRADUCTION ===
def translate_text(text, engine, source_lang, dest_lang, api_backend, api_url, llm_model, lang="FR"):
    m = MSG.get(lang, MSG["FR"])
    if not text: return ""
    if engine == "Google (Online)":
        if not HAS_TRANSLATOR: return m.get("err_trans_no_install", "⚠️ Error: deep-translator not installed.")
        lang_map = {"auto": "auto", "fr": "fr", "es": "es", "de": "de", "it": "it", "pt": "pt", "ru": "ru", "ja": "ja", "ko": "ko", "zh-CN": "zh-CN", "en": "en"}
        src = lang_map.get(source_lang, source_lang.split(" ")[0]) if source_lang else "auto"
        dst = lang_map.get(dest_lang, dest_lang.split(" ")[0]) if dest_lang else "en"
        try: 
            translator = GoogleTranslator(source=src, target=dst)
            parts = [p.strip() for p in text.split(',')]
            translated_parts = []
            for p in parts:
                if not p: continue
                try:
                    trans = translator.translate(p)
                    translated_parts.append(trans if trans else p)
                except:
                    translated_parts.append(p)
            return ", ".join(translated_parts)
        except Exception as e: return m.get("err_google_trans", "⚠️ Google Translate Error: {error}").format(error=str(e))
    else:
        return call_ai_api(f"Translate the following text from {source_lang} to {dest_lang}. ONLY output the translation, nothing else.\nText: {text}", llm_model, None, api_backend, api_url, 0.3, 1024, "You are a professional translator.")

def do_live_translation(caption, engine, dest_lang, api_backend, api_url, llm_model, lang):
    if not caption: return ""
    try:
        res = translate_text(caption, engine, "auto", dest_lang, api_backend, api_url, llm_model, lang)
        if res and res.startswith("⚠️"): return res
        return res
    except Exception as e:
        return f"Erreur: {e}"

def translate_entire_caption_action(dataset, filtered_dataset, idx, caption, engine, source_lang, api_backend, api_url, llm_model, tracked_words, lang):
    new_dataset = copy.deepcopy(dataset)
    new_filtered = [item for item in new_dataset if item['id'] in [x['id'] for x in filtered_dataset]]
    m = MSG.get(lang, MSG["FR"])

    if not caption: 
        cap, hl_html, wc = get_updated_viewer_data(new_filtered, idx, tracked_words, lang)
        return new_dataset, new_filtered, cap, hl_html, wc, m.get("trans_no_text", "Aucun texte")
        
    res = translate_text(caption, engine, source_lang, "en", api_backend, api_url, llm_model, lang)
    
    if res and res.startswith("⚠️"):
        gr.Warning(res)
        cap, hl_html, wc = get_updated_viewer_data(new_filtered, idx, tracked_words, lang)
        return new_dataset, new_filtered, cap, hl_html, wc, ""
    elif res:
        gr.Info(m.get("trans_entire_success", "✅ Caption complet traduit !"))
        if idx >= 0 and idx < len(new_filtered):
            new_filtered[idx]['caption'] = res
            new_dataset[new_filtered[idx]['id']]['caption'] = res
            txt_path = new_filtered[idx]['txt_path']
            if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
                shutil.copy2(txt_path, txt_path + ".bak")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(res)
                
            cap, hl_html, wc = get_updated_viewer_data(new_filtered, idx, tracked_words, lang)
            return new_dataset, new_filtered, cap, hl_html, wc, m.get("trans_to_en_success", "✅ Traduit")
        else:
            return new_dataset, new_filtered, res, get_highlighted_html(res, tracked_words), update_word_count(res, lang), m.get("trans_to_en_success", "✅ Traduit")
        
    cap, hl_html, wc = get_updated_viewer_data(new_filtered, idx, tracked_words, lang)
    return new_dataset, new_filtered, cap, hl_html, wc, ""

def trans_insert(text_to_trans, current_caption, engine, source_lang, api_backend, api_url, llm_model, lang):
    if not text_to_trans: return current_caption
    res = translate_text(text_to_trans, engine, source_lang, "en", api_backend, api_url, llm_model, lang)
    if res and not res.startswith("⚠️"):
        sep = ", " if current_caption and not current_caption.endswith(", ") else ""
        return current_caption + sep + res
    elif res and res.startswith("⚠️"):
        gr.Warning(res)
    return current_caption

# =========================================================================
# RESTE DES FONCTIONS STANDARD (Export, Doublons, IA, Stats)
# =========================================================================

def create_preview_df(old_dataset, new_dataset, lang):
    changes = []
    for old, new in zip(old_dataset, new_dataset):
        if old['caption'] != new['caption']:
            changes.append({"File" if lang=="EN" else "Fichier": old['img_name'], "Avant" if lang=="FR" else "Before": old['caption'], "Après" if lang=="FR" else "After": new['caption']})
            if len(changes) >= 10: break
    if not changes: return pd.DataFrame([{"Message": MSG[lang].get("no_changes", "No change")}])
    return pd.DataFrame(changes)

def batch_add(dataset, text, pos, selected_ids, search_text, current_idx, tracked_words, lang):
    if not text: 
        cap, hl, wc = get_updated_viewer_data(dataset, current_idx, tracked_words, lang)
        return dataset, dataset, dataset, MSG[lang].get("text_empty", ""), pd.DataFrame(), cap, hl, wc
    history = copy.deepcopy(dataset)
    count = 0
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        if pos in ["Début", "Start"]:
            sep = ", " if item['caption'] else ""
            item['caption'] = text + sep + item['caption']
        else:
            sep = ", " if item['caption'] and not item['caption'].endswith(", ") else ""
            item['caption'] = item['caption'] + sep + text
        count += 1
    save_all_captions(dataset)
    msg = MSG[lang].get("added_to", "Added").format(count=count)
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, create_preview_df(history, dataset, lang), cap, hl, wc

def batch_replace(dataset, old_text, new_text, use_regex, selected_ids, search_text, current_idx, tracked_words, lang):
    history = copy.deepcopy(dataset)
    count = 0
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        if use_regex:
            try:
                new_cap = re.sub(old_text, new_text, item['caption'])
                if new_cap != item['caption']: item['caption'] = new_cap; count += 1
            except: pass
        else:
            if old_text in item['caption']: item['caption'] = item['caption'].replace(old_text, new_text); count += 1
    save_all_captions(dataset)
    msg = MSG[lang].get("replaced_in", "Replaced").format(count=count)
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, create_preview_df(history, dataset, lang), cap, hl, wc

def batch_clean_commas(dataset, selected_ids, search_text, current_idx, tracked_words, lang):
    history = copy.deepcopy(dataset)
    count = 0
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        cap = item['caption']
        cap = re.sub(r'\s+', ' ', cap)
        cap = re.sub(r'\s*,\s*', ', ', cap)
        cap = re.sub(r'(,\s*){2,}', ', ', cap)
        cap = cap.strip(', ')
        if cap != item['caption']: item['caption'] = cap; count += 1
    save_all_captions(dataset)
    msg = MSG[lang].get("cleaned_in", "Cleaned").format(count=count)
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, create_preview_df(history, dataset, lang), cap, hl, wc

def batch_remove_duplicates(dataset, selected_ids, search_text, current_idx, tracked_words, lang):
    history = copy.deepcopy(dataset)
    count = 0
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        parts = [p.strip() for p in item['caption'].split(',')]
        seen = set(); new_parts = []
        for p in parts:
            if p.lower() not in seen and p != "": seen.add(p.lower()); new_parts.append(p)
        new_cap = ", ".join(new_parts)
        if new_cap != item['caption']: item['caption'] = new_cap; count += 1
    save_all_captions(dataset)
    msg = MSG[lang].get("dups_removed", "Removed").format(count=count)
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, create_preview_df(history, dataset, lang), cap, hl, wc

def batch_synonyms(dataset, target_tag, synonyms_str, selected_ids, search_text, current_idx, tracked_words, lang):
    history = copy.deepcopy(dataset)
    if not target_tag: 
        cap, hl, wc = get_updated_viewer_data(dataset, current_idx, tracked_words, lang)
        return dataset, dataset, dataset, MSG[lang].get("target_empty", ""), pd.DataFrame(), cap, hl, wc
    count = 0
    syn_list = [s.strip() for s in synonyms_str.split(',')] if synonyms_str else []
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        original = item['caption']
        tags = [t.strip() for t in original.split(',')]
        first_found = False; syn_idx = 0; new_tags = []
        for t in tags:
            if t.lower() == target_tag.strip().lower():
                if not first_found: first_found = True; new_tags.append(t)
                else:
                    if syn_list and syn_list[0]: new_tags.append(syn_list[syn_idx % len(syn_list)]); syn_idx += 1
            else: new_tags.append(t)
        new_cap = ", ".join([t for t in new_tags if t])
        if new_cap != original: item['caption'] = new_cap; count += 1
    save_all_captions(dataset)
    msg = MSG[lang].get("synonyms_replaced", "Replaced").format(count=count)
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, create_preview_df(history, dataset, lang), cap, hl, wc

def simulate_and_export(dataset, export_dir, config_df, is_simulation, selected_ids, strategy, max_images, lang):
    if not dataset: return MSG[lang].get("no_dataset", ""), [], None, None
    if config_df is None or config_df.empty: 
        config_df = pd.DataFrame([{MSG[lang].get("df_prio", "Prio"): 1, MSG[lang].get("df_kw", "Kw"): "", MSG[lang].get("df_tgt", "Tgt"): 0}])
    else:
        prio_col = "Priority" if "Priority" in config_df.columns else "Priorité"
        config_df[prio_col] = pd.to_numeric(config_df[prio_col], errors='coerce').fillna(999).astype(int)
        config_df = config_df.sort_values(by=prio_col)
    
    targets = {}; ordered_tags = []
    for _, row in config_df.iterrows():
        tag = str(row.get("Mot-clé", row.get("Keyword", ""))).strip().lower()
        if tag and tag not in ["aucun", "none"]:
            try: c = float(str(row.get("Cible %", row.get("Target %", 0))).replace('%', '').strip())
            except: c = 0.0
            targets[tag] = c
            ordered_tags.append(tag)

    base_pool = [item for item in dataset if not selected_ids or item['id'] in selected_ids]
    to_export = []
    limit = int(max_images)

    # `strategy` is the internal enum key (STRAT_*) from the radio's tuple
    # choices. Renaming labels in en.json can no longer change which branch
    # runs here.
    if strategy == STRAT_CLASSIC:
        for item in base_pool:
            if not ordered_tags or any(re.search(r'\b' + re.escape(t) + r'\b', item['caption'].lower()) for t in ordered_tags):
                to_export.append(item)
        if limit > 0: to_export = to_export[:limit]

    elif strategy == STRAT_PRIORITY:
        seen = set()
        lim = limit if limit > 0 else len(base_pool)
        for tag in ordered_tags:
            for item in base_pool:
                if len(to_export) >= lim: break
                if item['id'] not in seen and re.search(r'\b' + re.escape(tag) + r'\b', item['caption'].lower()):
                    to_export.append(item); seen.add(item['id'])
            if len(to_export) >= lim: break

    elif strategy == STRAT_BALANCING:
        relevant = [it for it in base_pool if not ordered_tags or any(re.search(r'\b'+re.escape(t)+r'\b', it['caption'].lower()) for t in ordered_tags)]
        lim = limit if limit > 0 else len(relevant)
        if lim > 0 and ordered_tags:
            needs = {tag: int((pct / 100.0) * lim) for tag, pct in targets.items() if pct > 0}
            if sum(needs.values()) == 0: to_export = relevant[:lim]
            else:
                available = relevant.copy()
                while len(to_export) < lim and available:
                    best_score = -9999; best_idx = -1
                    for i, item in enumerate(available):
                        cap = available[i]['caption'].lower(); score = 0; has_tag = False
                        for tag in ordered_tags:
                            if re.search(r'\b' + re.escape(tag) + r'\b', cap):
                                has_tag = True
                                if tag in needs: score += (10 * needs[tag]) if needs[tag] > 0 else -5
                        if has_tag and score > best_score: best_score = score; best_idx = i
                    if best_idx == -1: break
                    chosen = available.pop(best_idx)
                    to_export.append(chosen)
                    for tag in ordered_tags:
                        if re.search(r'\b' + re.escape(tag) + r'\b', chosen['caption'].lower()) and tag in needs: needs[tag] -= 1
        else: to_export = relevant[:lim]

    sim_stats = {t: 0 for t in ordered_tags}
    for item in to_export:
        cap = item['caption'].lower()
        for t in ordered_tags:
            if re.search(r'\b' + re.escape(t) + r'\b', cap): sim_stats[t] += 1
            
    pie_data = {k: v for k, v in sim_stats.items() if v > 0}
    if not pie_data:
        p_fig = px.pie(names=[MSG[lang].get("none", "Aucun")], values=[1], title=MSG[lang].get("no_tag_found", "Aucun tag trouvé"))
        b_fig = px.bar(x=[MSG[lang].get("none", "Aucun")], y=[0], title=MSG[lang].get("no_tag_found", "Aucun tag trouvé"))
    else:
        p_fig = px.pie(names=list(pie_data.keys()), values=list(pie_data.values()), title=MSG[lang].get("overall_dist", "Répartition Globale"))
        p_fig.update_traces(textposition='inside', textinfo='percent+label')
        b_fig = px.bar(x=list(pie_data.keys()), y=list(pie_data.values()), title=MSG[lang].get("occ_by_keyword", "Occurrences par Mot-clé"))

    gallery_preview = [item['img_path'] for item in to_export]
    
    if is_simulation:
        rep = MSG[lang].get("simul_res", "Simul: {count}").format(count=len(to_export))
        gr.Info("📊 Simulation terminée !")
        return rep, gallery_preview, p_fig, b_fig
    else:
        if not export_dir or str(export_dir).strip() == "": export_dir = os.path.join(os.getcwd(), "output", "dataset_final")
        if not os.path.exists(export_dir): os.makedirs(export_dir)
        for item in to_export:
            shutil.copy2(item['img_path'], os.path.join(export_dir, item['img_name']))
            shutil.copy2(item['txt_path'], os.path.join(export_dir, os.path.basename(item['txt_path'])))
        msg = MSG[lang].get("export_success", "Success").format(count=len(to_export), dest=export_dir)
        gr.Info(f"✅ Export réussi dans {export_dir}")
        return msg, gallery_preview, p_fig, b_fig

def analyze_dataset(dataset, tracked_words_str, lang):
    lang = lang or "FR"
    if not dataset: 
        empty_df = pd.DataFrame()
        return None, None, empty_df, "{}", empty_df, "{}", MSG[lang].get("no_dataset", "")
    if not tracked_words_str: 
        empty_conf = pd.DataFrame([{MSG[lang].get("df_prio", "Prio"): 1, MSG[lang].get("df_kw", "Kw"): "", MSG[lang].get("df_tgt", "Tgt"): 0}])
        empty_stats = pd.DataFrame([{MSG[lang].get("df_kw", "Kw"): "", MSG[lang].get("df_tgt", "Tgt"): ""}])
        return None, None, empty_stats, "{}", empty_conf, "{}", MSG[lang].get("enter_keywords", "")
    
    total_images = len(dataset)
    raw_words = [w.strip() for w in tracked_words_str.split(',') if w.strip()]
    targets = {}; stats = {}
    for w in raw_words:
        if ':' in w:
            parts = w.split(':'); word = parts[0].strip()
            try: targets[word] = float(parts[1].strip())
            except: targets[word] = 0.0
            stats[word] = 0
        else: stats[w] = 0
    for item in dataset:
        cap = item['caption'].lower()
        for word in stats.keys():
            if re.search(r'\b' + re.escape(word.lower()) + r'\b', cap): stats[word] += 1
    
    df_stats = []
    for word, count in stats.items():
        pct = (count / total_images) * 100 if total_images > 0 else 0
        row = {MSG[lang].get("df_kw", "Keyword"): word, "Count" if lang=="EN" else "Compte": count, "Current %" if lang=="EN" else "Actuel %": f"{pct:.1f}%"}
        if word in targets:
            row[MSG[lang].get("df_tgt", "Target %")] = f"{targets[word]}%"
            row["Diff" if lang=="EN" else "Écart"] = f"{'+' if (pct - targets[word])>0 else ''}{pct - targets[word]:.1f}%"
        else:
            row[MSG[lang].get("df_tgt", "Target %")] = "-"; row["Diff" if lang=="EN" else "Écart"] = "-"
        df_stats.append(row)
        
    df = pd.DataFrame(df_stats).sort_values(by="Count" if lang=="EN" else "Compte", ascending=False)
    df_json = df.to_json(orient='records')
    
    df_config = []
    for i, word in enumerate(stats.keys()):
        cible = targets.get(word, 0)
        df_config.append({MSG[lang].get("df_prio", "Priority"): i+1, MSG[lang].get("df_kw", "Keyword"): word, MSG[lang].get("df_tgt", "Target %"): cible})
    df_conf = pd.DataFrame(df_config)
    df_conf_json = df_conf.to_json(orient='records')

    pie_data = {k: v for k, v in stats.items() if v > 0}
    if not pie_data:
        fig_pie = px.pie(names=[MSG[lang].get("none", "None")], values=[1], title=MSG[lang].get("no_tag_found", "No tag"))
        fig_bar = px.bar(x=[MSG[lang].get("none", "None")], y=[0], title=MSG[lang].get("no_tag_found", "No tag"))
    else:
        fig_pie = px.pie(names=list(pie_data.keys()), values=list(pie_data.values()), title=MSG[lang].get("overall_dist", "Distribution"))
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_bar = px.bar(x=list(pie_data.keys()), y=list(pie_data.values()), title=MSG[lang].get("occ_by_keyword", "Occurrences"))
    
    return fig_pie, fig_bar, df, df_json, df_conf, df_conf_json, MSG[lang].get("stats_updated", "Updated")

def toggle_tracked_word(current_tracker, selected_text):
    if not selected_text: return gr.update()
    word = selected_text.strip(', ')
    if not word: return gr.update()
    current_list = [w.strip() for w in current_tracker.split(',') if w.strip()]
    existing = []; found = False
    for w in current_list:
        if w.split(':')[0].strip().lower() == word.lower(): found = True 
        else: existing.append(w)
    if not found: existing.append(word) 
    return ", ".join(existing)

def scan_duplicates_advanced(dataset, tolerance):
    if not HAS_IMAGEHASH:
        gr.Warning("Installez imagehash: pip install imagehash")
        return gr.update(choices=[], value=""), {}
    
    hashes = {}
    dups_pairs = []
    
    for item in dataset:
        try:
            img = Image.open(item['img_path'])
            h = imagehash.average_hash(img)
            
            found_dup = False
            for prev_h, prev_item in hashes.items():
                if abs(h - prev_h) <= int(tolerance):
                    pair_name = f"{prev_item['img_name']} VS {item['img_name']}"
                    dups_pairs.append({
                        "name": pair_name, 
                        "imgA": prev_item['img_path'], "imgB": item['img_path'],
                        "idA": prev_item['id'], "idB": item['id']
                    })
                    found_dup = True
                    break
            if not found_dup: hashes[h] = item
        except: pass
    
    if not dups_pairs:
        gr.Info("Aucun doublon visuel trouvé avec cette tolérance !")
        return gr.update(choices=[], value=""), {}
        
    choices = [p["name"] for p in dups_pairs]
    mapping = {p["name"]: p for p in dups_pairs}
    gr.Warning(f"{len(choices)} paires suspectes trouvées !")
    return gr.update(choices=choices, value=choices[0]), mapping

def load_duplicate_pair(pair_name, mapping):
    if not pair_name or pair_name not in mapping: return None, None, -1, -1
    data = mapping[pair_name]
    return data["imgA"], data["imgB"], data["idA"], data["idB"]

def delete_duplicate(dataset, filtered_dataset, id_to_delete, pair_name, mapping):
    if id_to_delete < 0: return dataset, filtered_dataset, gr.update(), mapping, "Erreur suppression"
    item_to_del = next((x for x in dataset if x['id'] == id_to_delete), None)
    if item_to_del:
        try:
            os.remove(item_to_del['img_path'])
            if os.path.exists(item_to_del['txt_path']): os.remove(item_to_del['txt_path'])
            dataset = [x for x in dataset if x['id'] != id_to_delete]
            filtered_dataset = [x for x in filtered_dataset if x['id'] != id_to_delete]
            gr.Info(f"Fichier {item_to_del['img_name']} supprimé.")
        except Exception as e:
            gr.Warning(f"Impossible de supprimer: {e}")
            
    if pair_name in mapping:
        del mapping[pair_name]
        
    choices = list(mapping.keys())
    val = choices[0] if choices else ""
    return dataset, filtered_dataset, gr.update(choices=choices, value=val), mapping, f"Supprimé. Reste {len(choices)} doublons."

def batch_rename_dataset(dataset, prefix):
    if not dataset or not prefix.strip(): return dataset, "Veuillez entrer un préfixe."
    prefix = prefix.strip()
    count = 1
    dir_path = os.path.dirname(dataset[0]['img_path'])
    for item in dataset:
        ext = os.path.splitext(item['img_name'])[1]
        new_img_name = f"{prefix}_{count:04d}{ext}"
        new_txt_name = f"{prefix}_{count:04d}.txt"
        new_img_path = os.path.join(dir_path, new_img_name)
        new_txt_path = os.path.join(dir_path, new_txt_name)
        try:
            os.rename(item['img_path'], new_img_path)
            if os.path.exists(item['txt_path']): os.rename(item['txt_path'], new_txt_path)
            item['img_name'] = new_img_name
            item['img_path'] = new_img_path
            item['txt_path'] = new_txt_path
        except: pass
        count += 1
    gr.Info("Renommage par lot effectué !")
    return dataset, "✅ Dataset renommé."

def batch_process_images(dataset, dest_folder, size, format_choice, crop_mode, handle_alpha):
    if not dataset: return "Aucun dataset."
    if not dest_folder: dest_folder = os.path.join(os.getcwd(), "processed_dataset")
    os.makedirs(dest_folder, exist_ok=True)
    count = 0
    target_size = int(size)
    for item in dataset:
        try:
            img = Image.open(item['img_path'])
            if handle_alpha and (img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P': img = img.convert('RGBA')
                bg.paste(img, (0,0), img)
                img = bg
            elif img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
                
            if crop_mode == "Smart Face Crop (OpenCV)" and HAS_CV2:
                img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                if len(faces) > 0:
                    x, y, w_face, h_face = faces[0]
                    center_x, center_y = x + w_face//2, y + h_face//2
                    w, h = img.size
                    min_dim = min(w, h)
                    left = max(0, center_x - min_dim//2)
                    top = max(0, center_y - min_dim//2)
                    right = min(w, left + min_dim)
                    bottom = min(h, top + min_dim)
                    if right - left < min_dim: left = right - min_dim
                    if bottom - top < min_dim: top = bottom - min_dim
                    img = img.crop((left, top, right, bottom))
                else:
                    w, h = img.size; min_dim = min(w, h)
                    img = img.crop(((w-min_dim)/2, (h-min_dim)/2, (w+min_dim)/2, (h+min_dim)/2))
            elif crop_mode == "1:1 (Carré Centre)":
                w, h = img.size; min_dim = min(w, h)
                img = img.crop(((w-min_dim)/2, (h-min_dim)/2, (w+min_dim)/2, (h+min_dim)/2))
            
            img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            ext = ".webp" if format_choice == "WebP" else ".jpg"
            new_name = os.path.splitext(item['img_name'])[0] + ext
            save_path = os.path.join(dest_folder, new_name)
            img.save(save_path, format="WEBP" if format_choice=="WebP" else "JPEG", quality=95)
            new_txt_name = os.path.splitext(item['img_name'])[0] + ".txt"
            shutil.copy2(item['txt_path'], os.path.join(dest_folder, new_txt_name))
            count += 1
        except Exception as e: print(f"Erreur pré-traitement sur {item['img_name']}: {e}")
    return f"✅ {count} images traitées avec succès !"

def update_advanced_stats(dataset):
    if not dataset: return None, None, "Aucun dataset", "Aucune contradiction"
    
    pairs = defaultdict(int)
    tag_counts = defaultdict(int)
    for item in dataset:
        tags = [t.strip().lower() for t in item['caption'].split(',') if t.strip()]
        for i in range(len(tags)):
            tag_counts[tags[i]] += 1
            for j in range(i+1, len(tags)):
                pairs[tuple(sorted([tags[i], tags[j]]))] += 1
                
    top_tags = [t for t, _ in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20]]
    
    z_data = []
    for t1 in top_tags:
        row = []
        for t2 in top_tags:
            if t1 == t2: row.append(0)
            else: row.append(pairs.get(tuple(sorted([t1, t2])), 0))
        z_data.append(row)
    fig_heatmap = px.imshow(z_data, x=top_tags, y=top_tags, color_continuous_scale='Viridis', title="Matrice de Co-occurrence")
    
    widths, heights, names = [], [], []
    for item in dataset:
        try:
            w, h = Image.open(item['img_path']).size
            widths.append(w); heights.append(h); names.append(item['img_name'])
        except: pass
    df_bucket = pd.DataFrame({'Largeur': widths, 'Hauteur': heights, 'Nom': names})
    fig_scatter = px.scatter(df_bucket, x='Largeur', y='Hauteur', hover_data=['Nom'], title="Distribution des Résolutions")
    fig_scatter.add_vline(x=1024, line_dash="dash", line_color="red"); fig_scatter.add_hline(y=1024, line_dash="dash", line_color="red")
    
    anti_pairs = []
    for i in range(len(top_tags)):
        for j in range(i+1, len(top_tags)):
            if pairs.get(tuple(sorted([top_tags[i], top_tags[j]])), 0) == 0:
                anti_pairs.append(f"[{top_tags[i]}] ❌ [{top_tags[j]}]")
    anti_txt = "\n".join(anti_pairs[:15]) if anti_pairs else "Tous les tops tags sont interconnectés."
    
    contradictions_found = []
    for item in dataset:
        cap = item['caption'].lower()
        for (a, b) in CONTRADICTIONS_LOGIQUES:
            if re.search(r'\b' + re.escape(a) + r'\b', cap) and re.search(r'\b' + re.escape(b) + r'\b', cap):
                contradictions_found.append(f"Image {item['img_name']} : Contient '{a}' ET '{b}'")
    contra_txt = "\n".join(contradictions_found) if contradictions_found else "✅ Aucune contradiction logique détectée."
    
    return fig_heatmap, fig_scatter, anti_txt, contra_txt

def find_orphans(dataset, lang):
    lang = lang or "FR"
    if not dataset: return MSG[lang].get("no_dataset", "")
    all_words = []
    for item in dataset:
        tags = [t.strip().lower() for t in item['caption'].split(',')]
        all_words.extend(tags)
    counts = Counter(all_words)
    orphans = [tag for tag, count in counts.items() if count == 1 and len(tag) > 2]
    if not orphans: return MSG[lang].get("no_orphans", "No orphans")
    return MSG[lang].get("unique_tags", "Unique:\n") + ", ".join(sorted(orphans))

def auto_fill_top_tags(dataset):
    if not dataset: return ""
    all_words = []
    for item in dataset:
        tags = [t.strip().lower() for t in item['caption'].split(',')]
        all_words.extend([t for t in tags if t])
    counts = Counter(all_words)
    return ", ".join([tag for tag, count in counts.most_common(20)])

def generate_civitai_format(df):
    if df is None or df.empty: return ""
    md = "| " + " | ".join(df.columns) + " |\n"
    md += "|" + "|".join(["---" for _ in df.columns]) + "|\n"
    for _, row in df.iterrows(): md += "| " + " | ".join(str(x) for x in row.values) + " |\n"
    gr.Info("✅ Format CivitAI généré ! Copiez le texte ci-dessous.")
    return md

# === Recettes / Tables Helpers (Pour l'Export) ===
def df_to_tracked_words(df):
    if df is None or df.empty: return ""
    words = []
    for _, row in df.iterrows():
        mot = str(row.get("Mot-clé", row.get("Keyword", ""))).strip()
        if not mot or mot.lower() in ["aucun", "none"]: continue
        cible = str(row.get("Cible %", row.get("Target %", ""))).replace('%', '').strip()
        if cible and cible != "-" and cible != "0.0" and cible != "0": words.append(f"{mot}:{cible}")
        else: words.append(mot)
    return ", ".join(words)

def norm_tracked_words(s):
    if not s or not isinstance(s, str): return ""
    return ",".join(sorted([w.strip().lower() for w in s.split(',') if w.strip()]))

def safe_df_to_tracked_words(df, current_str):
    new_str = df_to_tracked_words(df)
    if norm_tracked_words(new_str) == norm_tracked_words(current_str): return gr.update()
    return new_str

def get_row_index(evt: gr.SelectData, state_json):
    row_idx = evt.index[0]
    if not state_json or state_json == "{}": return row_idx, gr.update(), gr.update()
    df = pd.read_json(io.StringIO(state_json), orient='records')
    if df.empty or row_idx >= len(df): return row_idx, gr.update(), gr.update()
    prio_col = "Priorité" if "Priorité" in df.columns else "Priority"
    tgt_col = "Cible %" if "Cible %" in df.columns else "Target %"
    prio_val = str(df.at[row_idx, prio_col])
    tgt_val = str(df.at[row_idx, tgt_col]).replace('%', '')
    try: tgt_val = float(tgt_val)
    except: tgt_val = 0.0
    return row_idx, prio_val, tgt_val

def apply_quick_prio(new_prio, row_idx, state_json):
    if row_idx < 0 or not state_json or state_json == "{}": return gr.update(), state_json, gr.update(), row_idx
    df = pd.read_json(io.StringIO(state_json), orient='records')
    if df.empty or row_idx >= len(df): return gr.update(), state_json, gr.update(), row_idx
    prio_col = "Priorité" if "Priorité" in df.columns else "Priority"
    try: new_prio_int = int(new_prio)
    except: return gr.update(), state_json, gr.update(), row_idx
    max_prio = len(df)
    if new_prio_int < 1: new_prio_int = 1
    if new_prio_int > max_prio: new_prio_int = max_prio
    old_prio = df.at[row_idx, prio_col]
    if old_prio == new_prio_int: return gr.update(), state_json, gr.update(), row_idx
    conflict_mask = df[prio_col] == new_prio_int
    if conflict_mask.any():
        conflict_idx = conflict_mask.idxmax()
        df.at[conflict_idx, prio_col] = old_prio
    df.at[row_idx, prio_col] = new_prio_int
    df = df.sort_values(by=prio_col).reset_index(drop=True)
    df[prio_col] = range(1, len(df) + 1)
    new_row_idx = df.index[df[prio_col] == new_prio_int].tolist()[0]
    new_json = df.to_json(orient='records')
    return df, new_json, df_to_tracked_words(df), new_row_idx

def apply_quick_target(new_tgt, row_idx, state_json):
    if row_idx < 0 or not state_json or state_json == "{}": return gr.update(), state_json, gr.update()
    df = pd.read_json(io.StringIO(state_json), orient='records')
    if df.empty or row_idx >= len(df): return gr.update(), state_json, gr.update()
    tgt_col = "Cible %" if "Cible %" in df.columns else "Target %"
    old_tgt = str(df.at[row_idx, tgt_col]).replace('%', '')
    try: old_tgt = float(old_tgt)
    except: old_tgt = 0.0
    if new_tgt is None: new_tgt = 0.0
    if old_tgt == new_tgt: return gr.update(), state_json, gr.update()
    df.at[row_idx, tgt_col] = new_tgt
    new_json = df.to_json(orient='records')
    return df, new_json, df_to_tracked_words(df)

def df_move_up(df, row_idx):
    if df is None or df.empty or row_idx <= 0 or row_idx >= len(df): return df, row_idx, df_to_tracked_words(df)
    d = df.to_dict('records')
    d[row_idx], d[row_idx-1] = d[row_idx-1], d[row_idx]
    ndf = pd.DataFrame(d)
    col = "Priorité" if "Priorité" in ndf.columns else "Priority"
    ndf[col] = range(1, len(ndf)+1)
    return ndf, row_idx - 1, df_to_tracked_words(ndf)

def df_move_down(df, row_idx):
    if df is None or df.empty or row_idx < 0 or row_idx >= len(df)-1: return df, row_idx, df_to_tracked_words(df)
    d = df.to_dict('records')
    d[row_idx], d[row_idx+1] = d[row_idx+1], d[row_idx]
    ndf = pd.DataFrame(d)
    col = "Priorité" if "Priorité" in ndf.columns else "Priority"
    ndf[col] = range(1, len(ndf)+1)
    return ndf, row_idx + 1, df_to_tracked_words(ndf)

def df_delete_row(df, row_idx):
    if df is None or df.empty or row_idx < 0 or row_idx >= len(df): return df, -1, df_to_tracked_words(df)
    d = df.to_dict('records')
    d.pop(row_idx)
    ndf = pd.DataFrame(d) if d else pd.DataFrame(columns=df.columns)
    if not ndf.empty:
        col = "Priorité" if "Priorité" in ndf.columns else "Priority"
        ndf[col] = range(1, len(ndf)+1)
    return ndf, -1, df_to_tracked_words(ndf)

def handle_df_edit(new_df, old_df):
    if new_df is None or new_df.empty: return new_df, new_df, df_to_tracked_words(new_df)
    prio_col = "Priorité" if "Priorité" in new_df.columns else "Priority"
    if old_df is not None and not old_df.empty and len(new_df) == len(old_df):
        try:
            new_series = pd.to_numeric(new_df[prio_col], errors='coerce').fillna(999).astype(int)
            old_series = pd.to_numeric(old_df[prio_col], errors='coerce').fillna(999).astype(int)
            diff_mask = new_series != old_series
            if diff_mask.any():
                changed_idx = diff_mask.idxmax()
                new_prio = new_series.iloc[changed_idx]
                old_prio = old_series.iloc[changed_idx]
                max_prio = len(new_df)
                if new_prio < 1: new_prio = 1
                if new_prio > max_prio: new_prio = max_prio
                new_df.at[changed_idx, prio_col] = new_prio
                new_series.iloc[changed_idx] = new_prio
                conflict_mask = (new_series == new_prio) & (new_series.index != changed_idx)
                if conflict_mask.any():
                    conflict_idx = conflict_mask.idxmax()
                    new_df.at[conflict_idx, prio_col] = old_prio
        except Exception: pass
    try:
        new_df[prio_col] = pd.to_numeric(new_df[prio_col], errors='coerce').fillna(999).astype(int)
        new_df = new_df.sort_values(by=prio_col).reset_index(drop=True)
        new_df[prio_col] = range(1, len(new_df) + 1)
    except: pass
    return new_df, new_df, df_to_tracked_words(new_df)

def handle_recipe_df_safe(new_df, state_json, current_str):
    if new_df is None or new_df.empty: return gr.update(), "{}", gr.update()
    new_json = new_df.to_json(orient='records')
    if new_json == state_json: return gr.update(), state_json, gr.update()
    old_df = pd.read_json(io.StringIO(state_json), orient='records') if state_json != "{}" else pd.DataFrame()
    processed_df, _, new_str = handle_df_edit(new_df, old_df)
    processed_json = processed_df.to_json(orient='records')
    str_update = new_str if norm_tracked_words(new_str) != norm_tracked_words(current_str) else gr.update()
    return processed_df, processed_json, str_update

def handle_stats_df_safe(new_df, state_json, current_str):
    if new_df is None or new_df.empty: return gr.update(), "{}", gr.update()
    new_json = new_df.to_json(orient='records')
    if new_json == state_json: return gr.update(), state_json, gr.update()
    new_str = df_to_tracked_words(new_df)
    str_update = new_str if norm_tracked_words(new_str) != norm_tracked_words(current_str) else gr.update()
    return gr.update(), new_json, str_update

def handle_drag_and_drop(dnd_data, current_df):
    if not dnd_data or current_df is None or current_df.empty: return current_df, gr.update()
    try:
        old_idx, new_idx = map(int, dnd_data.split(','))
        if old_idx < 0 or old_idx >= len(current_df) or new_idx < 0 or new_idx >= len(current_df): return current_df, gr.update()
        df_list = current_df.to_dict('records')
        item = df_list.pop(old_idx)
        df_list.insert(new_idx, item)
        new_df = pd.DataFrame(df_list)
        prio_col = "Priorité" if "Priorité" in new_df.columns else "Priority"
        new_df[prio_col] = range(1, len(new_df) + 1)
        return new_df, df_to_tracked_words(new_df)
    except: return current_df, gr.update()

def load_ai_recipes():
    if os.path.exists(AI_RECIPES_FILE):
        with open(AI_RECIPES_FILE, 'r') as f: return json.load(f)
    return {"Default Flux Style": "Réécris ces tags en une phrase naturelle parfaite pour le modèle Flux : {tags}"}

def save_ai_recipe(name, prompt):
    if not name: return gr.update()
    recipes = load_ai_recipes()
    recipes[name] = prompt
    with open(AI_RECIPES_FILE, 'w') as f: json.dump(recipes, f)
    gr.Info("Template IA sauvegardé !")
    return gr.update(choices=list(recipes.keys()), value=name)

def apply_ai_recipe(name): return load_ai_recipes().get(name, "")

AI_ACTION_DESCRIPTIONS = {
    "Auto-Taggage / Super OCR (VLM)": "**Vision :** Analyse complète de l'image et extraction du texte.",
    "Reality Check & Hallucinations (VLM)": "**Vision :** Supprime les tags inexistants dans l'image réelle.",
    "Concept Isolator (Spécial LoRA)": "**Vision :** Décrit tout SAUF le sujet central.",
    "Traducteur Visuel (Booru ↔ Phrase Naturelle)": "**Texte :** Convertit des tags bruts en une belle phrase.",
    "Tag Sorting & Standardisation": "**Texte :** Ordonne l'importance des tags et corrige l'orthographe.",
    "Traduction Automatique (Vers Anglais)": "**Texte :** Traduit proprement vers l'anglais.",
    "✨ Prompt Personnalisé (Texte/Vision)": "**Custom :** Utilisez le champ 'Prompt Personnalisé' ci-dessous."
}

def update_ai_action_desc(action):
    show_custom = action == "✨ Prompt Personnalisé (Texte/Vision)"
    desc = AI_ACTION_DESCRIPTIONS.get(action, "")
    return f"<div class='ai-desc-box'>ℹ️ {desc}</div>", gr.update(visible=show_custom), gr.update(visible=show_custom)

def call_ai_api(prompt, model, image_path, api_backend, api_url, temp, ctx, sys_prompt):
    api_url = str(api_url).strip()
    if not api_url.startswith("http"): api_url = "http://" + api_url
    b64 = None
    if image_path:
        with open(image_path, "rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
    if api_backend == BACKEND_OLLAMA:
        if not api_url.endswith("/api/generate") and not api_url.endswith("/api/chat"): api_url = api_url.rstrip("/") + "/api/generate"
        payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": float(temp), "num_ctx": int(ctx)}}
        if sys_prompt: payload["system"] = str(sys_prompt).strip()
        if b64: payload["images"] = [b64]
        try:
            response = requests.post(api_url, json=payload, timeout=180)
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except Exception as e: return f"Erreur API Ollama: {e}"
    else:
        if api_url.endswith("/"): api_url = api_url[:-1]
        if not api_url.endswith("/v1/chat/completions"): api_url = api_url + "/v1/chat/completions"
        messages = []
        if sys_prompt: messages.append({"role": "system", "content": str(sys_prompt).strip()})
        if b64: messages.append({"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]})
        else: messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "temperature": float(temp), "max_tokens": int(ctx)}
        try:
            response = requests.post(api_url, json=payload, timeout=180)
            response.raise_for_status()
            return response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        except Exception as e: return f"Erreur API OpenAI: {e}"

def process_ai_action(dataset, selected_ids, search_text, action, custom_prompt, injection_mode, use_vision_for_custom, vlm_model, llm_model, api_backend, api_url, temp, ctx, sys_prompt, current_idx, tracked_words, lang):
    if not dataset: return dataset, dataset, dataset, "Dataset vide.", extract_all_tags(dataset), "", get_highlighted_html("", tracked_words), ""
    history = copy.deepcopy(dataset)
    count = 0; errors = []
    for item in dataset:
        if selected_ids and item['id'] not in selected_ids: continue
        current_cap = item['caption']; new_cap = current_cap; res = ""
        try:
            if action == "Auto-Taggage / Super OCR (VLM)": res = call_ai_api("Décris cette image en détail (virgules). Ajoute le texte lu sous la forme text: \"le texte\".", vlm_model, item['img_path'], api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "Reality Check & Hallucinations (VLM)": res = call_ai_api(f"Tags actuels: '{current_cap}'. Ne renvoie QUE les tags réellement présents.", vlm_model, item['img_path'], api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "Concept Isolator (Spécial LoRA)": res = call_ai_api("Décris l'arrière-plan et le style, NE DÉCRIS PAS le sujet principal.", vlm_model, item['img_path'], api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "Traducteur Visuel (Booru ↔ Phrase Naturelle)": res = call_ai_api(f"Transforme en phrase anglaise fluide pour Flux : {current_cap}", llm_model, None, api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "Traduction Automatique (Vers Anglais)": res = call_ai_api(f"Translate into English, keep comma format: {current_cap}", llm_model, None, api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "Tag Sorting & Standardisation": res = call_ai_api(f"Ordonne (Sujet, Vêtements, Fond) et corrige: {current_cap}", llm_model, None, api_backend, api_url, temp, ctx, sys_prompt)
            elif action == "✨ Prompt Personnalisé (Texte/Vision)":
                model_to_use = vlm_model if use_vision_for_custom else llm_model
                img_path_to_use = item['img_path'] if use_vision_for_custom else None
                res = call_ai_api(custom_prompt.replace("{tags}", current_cap), model_to_use, img_path_to_use, api_backend, api_url, temp, ctx, sys_prompt)
            
            if res.startswith("Erreur API"): errors.append(item['img_name']); gr.Warning(res); continue
            if injection_mode == "Remplacer tout" or action != "✨ Prompt Personnalisé (Texte/Vision)": new_cap = res
            elif injection_mode == "Ajouter au début": new_cap = res + ", " + current_cap if current_cap else res
            elif injection_mode == "Ajouter à la fin": new_cap = current_cap + ", " + res if current_cap else res
            
            if new_cap != current_cap: item['caption'] = new_cap; count += 1
        except: errors.append(item['img_name'])
    save_all_captions(dataset)
    msg = f"✅ IA Appliquée ({count} modifiés)."
    if errors: msg += f" ⚠️ Échecs sur {len(errors)} fichiers."
    gr.Info(msg)
    filtered_dataset = [item for item in dataset if search_text.lower() in item['caption'].lower()] if search_text else dataset
    
    cap, hl, wc = get_updated_viewer_data(filtered_dataset, current_idx, tracked_words, lang)
    return dataset, filtered_dataset, history, msg, extract_all_tags(dataset), cap, hl, wc

def analyze_bias(dataset, llm_model, api_backend, api_url, temp, ctx, sys_prompt):
    if not dataset: return "Aucun dataset."
    all_caps = " | ".join([it['caption'] for it in dataset[:50]]) 
    return call_ai_api(f"Tu es un expert en entraînement IA. Échantillon de mon dataset : {all_caps}. Bref rapport des biais potentiels (poses, diversité) et conseils.", llm_model, None, api_backend, api_url, temp, ctx, sys_prompt)

# ==========================================
# INTERFACE GRADIO
# ==========================================

with gr.Blocks(title="IMG Dataset Refiner v4.0 Pro", css=css_code) as app:
    
    dataset_state = gr.State([])
    filtered_state = gr.State([])
    history_state = gr.State([])
    current_idx_state = gr.State(-1) 
    selected_indices_state = gr.State([]) 
    config_df_state = gr.State("{}") 
    stats_df_state = gr.State("{}")
    recipe_selected_row = gr.State(-1)
    
    # State pour la bibliothèque Custom HTML
    lib_state = gr.State([])
    
    dup_mapping_state = gr.State({})
    dup_idA = gr.State(-1)
    dup_idB = gr.State(-1)
    
    dummy_selection = gr.Textbox(visible=False, elem_id="dummy_selection")
    ui_hidden_sync_input = gr.Textbox(value="{}", elem_id="hidden_sync_input")
    ui_hidden_sync_btn = gr.Button(elem_id="hidden_sync_btn")
    ui_hidden_calc_btn = gr.Button(elem_id="hidden_calc_btn")
    ui_hidden_dnd_input = gr.Textbox(elem_id="hidden_dnd_input")
    ui_hidden_dnd_btn = gr.Button(elem_id="hidden_dnd_btn")
    ui_hidden_tags_input = gr.Textbox(elem_id="hidden_tags_input")
    
    # Inputs cachés pour le module Custom Library
    ui_hidden_lib_toggle_input = gr.Textbox(elem_id="hidden_lib_toggle_input")
    ui_hidden_lib_toggle_btn = gr.Button(elem_id="hidden_lib_toggle_btn")
    ui_hidden_lib_delete_input = gr.Textbox(elem_id="hidden_lib_delete_input")
    ui_hidden_lib_delete_btn = gr.Button(elem_id="hidden_lib_delete_btn")
    
    # Fork: English-only at runtime. fr.json still loads (it's referenced
    # by change_language-less default-lookups in handlers) but the lang_radio
    # is hidden and the dynamic-translation callback was removed in Phase 3.
    t_init = UI_T.get("EN", UI_T.get("FR", {}))

    with gr.Row():
        with gr.Column(scale=2):
            lang_radio = gr.Radio(["FR", "EN"], value="EN", label="Language / Langue", visible=False)
            ui_title = gr.Markdown(t_init.get("title", ""))
            
            ui_guide_acc = gr.Accordion(t_init.get("guide_title", ""), open=False)
            with ui_guide_acc:
                ui_guide_text = gr.Markdown(t_init.get("guide_text", ""))
            
            with gr.Row():
                dir_input = gr.Textbox(placeholder="C:\\mon\\dataset", show_label=False, scale=4, elem_id="dataset_dir_input")
                ui_browse_btn = gr.Button(t_init.get("browse", ""), scale=1, elem_id="browse_btn")
            ui_load_btn = gr.Button(t_init.get("load", ""), variant="primary", elem_id="load_btn")
            ui_status_text = gr.Markdown(t_init.get("status_wait", ""))
            
        with gr.Column(scale=3):
            ui_recipe_global = gr.Markdown(t_init.get("recipe_global", ""))
            with gr.Row():
                ui_recipes_dropdown = gr.Dropdown(choices=list(load_recipes().keys()), label=t_init.get("recipes_dd", ""), scale=2)
                ui_recipe_name = gr.Textbox(label=t_init.get("recipe_name", ""), scale=1)
                ui_save_recipe_btn = gr.Button(t_init.get("save_recipe", ""), scale=1)
            ui_tracked_words = gr.Textbox(show_label=False, placeholder=t_init.get("tracked_ph", ""), lines=2, elem_id="tracked_words_input")

    gr.Markdown("---")
    
    with gr.Row():
        with gr.Column(scale=0, elem_id="left_panel") as left_panel:
            ui_gallery_title = gr.Markdown(t_init.get("gallery_title", ""))
            ui_search_box = gr.Textbox(label=t_init.get("search", ""), placeholder=t_init.get("search_ph", ""))
            ui_sort_order = gr.Radio(["A-Z", "Z-A"], value="A-Z", label="Trier / Sort")
            
            with gr.Row():
                ui_multi_select_cb = gr.Checkbox(label=t_init.get("multi_cb", ""), value=False, interactive=True, elem_id="multi_cb", scale=2)
                ui_clear_sel_btn = gr.Button(t_init.get("clear_sel", ""), elem_id="clear_sel_btn", scale=1)
                
            ui_selection_status = gr.Markdown("**...**")
            ui_gallery_cols = gr.Slider(minimum=1, maximum=6, step=1, value=2, label=t_init.get("cols", ""), interactive=True)
            gallery = gr.Gallery(label="Dataset", columns=2, rows=6, height=750, object_fit="contain", allow_preview=False, elem_id="main_gallery")
            
        with gr.Column(scale=1):
            ui_toggle_panel_btn = gr.Button(t_init.get("hide_gal", ""), elem_id="toggle_gallery_btn", variant="secondary", size="sm")
            
            with gr.Tabs():
                ui_tab_view = gr.Tab(t_init.get("tab_view", ""))
                with ui_tab_view:
                    with gr.Row():
                        ui_btn_prev = gr.Button(t_init.get("btn_prev", ""), elem_id="prev_btn")
                        ui_btn_next = gr.Button(t_init.get("btn_next", ""), elem_id="next_btn")
                    ui_viewer_status = gr.Markdown("**...**")
                    with gr.Row():
                        current_img = gr.Image(interactive=False, type="filepath", height=350, elem_id="viewer_area")
                        with gr.Column(elem_id="viewer_area_text"):
                            highlight_preview = gr.HTML()
                            word_counter = gr.HTML("<div style='color:green;'>0</div>")
                            ui_viewer_shortcuts = gr.Markdown(t_init.get("shortcuts", ""))
                            ui_toggle_tag_btn = gr.Button(t_init.get("toggle_stat", ""), variant="secondary", elem_id="toggle_tag_btn")
                    
                    current_caption = gr.Textbox(show_label=False, lines=4, elem_id="viewer_caption_area")
                    ui_live_translation_output = gr.Textbox(label=t_init.get("live_trans_label", ""), interactive=False, lines=3, elem_id="live_translation_preview")
                    
                    ui_save_single_btn = gr.Button(t_init.get("save_cap", ""), variant="primary", elem_id="save_single_btn")
                    ui_single_save_status = gr.Markdown()
                    
                    with gr.Group():
                        ui_trans_module_title = gr.Markdown(t_init.get("trans_module_title", ""))
                        with gr.Row():
                            with gr.Column(scale=2):
                                ui_trans_engine = gr.Radio(["Google (Online)", "IA Locale (Ollama/LM Studio)"], label=t_init.get("trans_engine", ""), value="Google (Online)")
                            with gr.Column(scale=1):
                                ui_trans_source = gr.Dropdown(["auto", "fr", "es", "de", "it", "pt", "ru", "ja", "ko", "zh-CN"], label=t_init.get("trans_source", ""), value="auto")
                            with gr.Column(scale=1):
                                ui_trans_target = gr.Dropdown(["fr", "en", "es", "de", "it", "pt", "ru", "ja", "ko", "zh-CN"], label=t_init.get("trans_target", ""), value="fr")
                        
                        ui_btn_translate_entire_caption = gr.Button(t_init.get("btn_translate_entire", ""), elem_id="btn_translate_entire")
                        gr.Markdown("---")
                        ui_trans_insert_title = gr.Markdown(t_init.get("trans_insert_title", ""))
                        with gr.Row():
                            with gr.Column(scale=3):
                                ui_trans_input = gr.Textbox(show_label=False, placeholder=t_init.get("trans_input_ph", ""), lines=1)
                            with gr.Column(scale=1):
                                ui_btn_insert_trans = gr.Button(t_init.get("btn_insert_trans", ""))

                ui_tab_batch = gr.Tab(t_init.get("tab_batch", ""))
                with ui_tab_batch:
                    ui_btn_undo = gr.Button(t_init.get("btn_undo", ""), variant="stop")
                    ui_batch_status = gr.Markdown()
                    with gr.Row():
                        with gr.Group():
                            ui_btn_clean_com = gr.Button(t_init.get("btn_clean_com", ""))
                            ui_btn_clean_dup = gr.Button(t_init.get("btn_clean_dup", ""))
                    ui_preview_table = gr.Dataframe(label=t_init.get("df_preview", ""), interactive=False, elem_id="preview_table")

                ui_tab_prep = gr.Tab(t_init.get("tab_prep", ""))
                with ui_tab_prep:
                    with gr.Row():
                        with gr.Column(scale=1):
                            ui_dup_title = gr.Markdown(t_init.get("dup_title", ""))
                            ui_hash_tol = gr.Slider(0, 20, 5, step=1, label=t_init.get("hash_tol", ""))
                            btn_scan_dups = gr.Button(t_init.get("btn_scan_dups", ""))
                            dup_dropdown = gr.Dropdown(label=t_init.get("dup_dd", ""), interactive=True)
                            with gr.Row():
                                dup_img_A = gr.Image(label="Image A", interactive=False, height=200)
                                dup_img_B = gr.Image(label="Image B", interactive=False, height=200)
                            with gr.Row():
                                btn_del_A = gr.Button(t_init.get("btn_del_A", ""), variant="stop")
                                btn_del_B = gr.Button(t_init.get("btn_del_B", ""), variant="stop")
                            dup_status = gr.Markdown()
                        with gr.Column(scale=1):
                            ui_rename_title = gr.Markdown(t_init.get("rename_title", ""))
                            ui_rename_prefix = gr.Textbox(label=t_init.get("rename_prefix", ""), placeholder="concept")
                            btn_rename = gr.Button(t_init.get("btn_rename", ""))
                            gr.Markdown("---")
                            ui_resize_title = gr.Markdown(t_init.get("resize_title", ""))
                            prep_size = gr.Dropdown(["512", "768", "1024", "1536"], value="1024", label=t_init.get("prep_size", ""))
                            prep_format = gr.Dropdown(["WebP", "JPEG"], value="WebP", label=t_init.get("prep_format", ""))
                            prep_crop = gr.Dropdown(["Conserver Ratio", "1:1 (Carré Centre)", "Smart Face Crop (OpenCV)"], value="Conserver Ratio", label=t_init.get("prep_crop", ""))
                            prep_alpha = gr.Checkbox(value=True, label=t_init.get("prep_alpha", ""))
                            prep_dest = gr.Textbox(label=t_init.get("prep_dest", ""), placeholder="...")
                            btn_prep = gr.Button(t_init.get("btn_prep", ""), variant="primary")
                            prep_status = gr.Markdown()

                ui_tab_ai = gr.Tab(t_init.get("tab_ai", ""))
                with ui_tab_ai:
                    with gr.Row():
                        with gr.Column(scale=1):
                            ui_ai_conf_title = gr.Markdown(t_init.get("ai_conf_title", ""))
                            api_backend = gr.Radio(
                                choices=[("Ollama", BACKEND_OLLAMA), ("OpenAI-compatible (LM Studio / GGUF)", BACKEND_OPENAI)],
                                label=t_init.get("api_backend", ""), value=BACKEND_OLLAMA,
                            )
                            vlm_model = gr.Textbox(value="llava", label=t_init.get("vlm_model", ""))
                            llm_model = gr.Textbox(value="llama3.1", label=t_init.get("llm_model", ""))
                            with gr.Accordion(t_init.get("ai_adv_acc", ""), open=False) as ui_ai_adv_acc:
                                api_url_input = gr.Textbox(value=DEFAULT_OLLAMA_URL, label=t_init.get("api_url_input", ""))
                                ai_temp = gr.Slider(minimum=0.0, maximum=2.0, value=0.7, step=0.1, label=t_init.get("ai_temp", ""))
                                ai_ctx = gr.Number(value=4096, label=t_init.get("ai_ctx", ""))
                                ai_sys = gr.Textbox(label=t_init.get("ai_sys", ""), lines=2)
                        with gr.Column(scale=2):
                            ui_ai_act_title = gr.Markdown(t_init.get("ai_act_title", ""))
                            ai_action_dropdown = gr.Dropdown([
                                "Auto-Taggage / Super OCR (VLM)",
                                "Reality Check & Hallucinations (VLM)",
                                "Concept Isolator (Spécial LoRA)",
                                "Traducteur Visuel (Booru ↔ Phrase Naturelle)",
                                "Tag Sorting & Standardisation",
                                "Traduction Automatique (Vers Anglais)",
                                "✨ Prompt Personnalisé (Texte/Vision)"
                            ], label=t_init.get("ai_action_dd", ""), value="Auto-Taggage / Super OCR (VLM)")
                            ai_action_desc = gr.HTML()
                            with gr.Group(visible=False) as custom_prompt_group:
                                with gr.Row():
                                    ai_template_dd = gr.Dropdown(choices=list(load_ai_recipes().keys()), label=t_init.get("ai_tpl_dd", ""))
                                    ai_template_name = gr.Textbox(label=t_init.get("ai_tpl_name", ""))
                                    btn_save_template = gr.Button(t_init.get("btn_save_tpl", ""))
                                custom_prompt_input = gr.Textbox(label=t_init.get("custom_prompt_input", ""), placeholder="...", lines=3)
                                use_vision_for_custom = gr.Checkbox(label=t_init.get("use_vision_custom", ""))
                            with gr.Group(visible=False) as injection_group:
                                injection_mode = gr.Radio(["Remplacer tout", "Ajouter au début", "Ajouter à la fin"], label=t_init.get("injection_mode", ""), value="Remplacer tout")
                            with gr.Row():
                                btn_run_ai = gr.Button(t_init.get("btn_run_ai", ""), variant="primary")
                                btn_undo_ai = gr.Button(t_init.get("btn_undo_ai", ""), variant="stop")
                            ai_status = gr.Markdown()
                    gr.Markdown("---")
                    ui_bias_title = gr.Markdown(t_init.get("bias_title", ""))
                    btn_bias = gr.Button(t_init.get("btn_bias", ""), variant="secondary")
                    txt_bias = gr.Textbox(label=t_init.get("txt_bias", ""), lines=5, interactive=False)

                ui_tab_export = gr.Tab(t_init.get("tab_export", ""))
                with ui_tab_export:
                    with gr.Row():
                        with gr.Column(scale=1):
                            ui_exp_edit = gr.Markdown(t_init.get("exp_edit", ""))
                            with gr.Row():
                                ui_btn_up = gr.Button(t_init.get("btn_up", ""), variant="secondary", size="sm", elem_id="btn_move_up")
                                ui_btn_down = gr.Button(t_init.get("btn_down", ""), variant="secondary", size="sm", elem_id="btn_move_down")
                                ui_btn_del = gr.Button(t_init.get("btn_del", ""), variant="stop", size="sm")
                            with gr.Row():
                                ui_quick_prio = gr.Dropdown(label=t_init.get("quick_prio", ""), choices=[str(i) for i in range(1, 101)], allow_custom_value=True, scale=1)
                                ui_quick_target = gr.Number(label=t_init.get("quick_tgt", ""), scale=1)
                                
                            ui_export_config_df = gr.Dataframe(headers=t_init.get("exp_df_headers", []), interactive=True, type="pandas", row_count=(1, "dynamic"), col_count=(3, "fixed"), elem_id="export_config_df")
                            _sc = t_init.get("strat_choices", ["Classic Filter", "Auto Balancing (Percentages)", "Priority"])
                            ui_strategy_radio = gr.Radio(
                                choices=[(_sc[0], STRAT_CLASSIC), (_sc[1], STRAT_BALANCING), (_sc[2], STRAT_PRIORITY)],
                                value=STRAT_CLASSIC,
                                label=t_init.get("strat", ""),
                            )
                            ui_max_img_input = gr.Number(label=t_init.get("max_img", ""), value=0, precision=0)
                            ui_export_dir = gr.Textbox(label=t_init.get("dest_folder", ""), placeholder=t_init.get("dest_ph", ""))
                            with gr.Row():
                                ui_btn_simul = gr.Button(t_init.get("btn_simul", ""), variant="secondary")
                                ui_btn_exp = gr.Button(t_init.get("btn_exp", ""), variant="primary")
                        with gr.Column(scale=1):
                            ui_export_status = gr.Markdown()
                            export_pie = gr.Plot(label=t_init.get("overall_dist", ""))
                    ui_exp_gal = gr.Markdown(t_init.get("exp_gal", ""))
                    export_gallery = gr.Gallery(columns=8, rows=2, height=250, object_fit="contain", allow_preview=False)

                ui_tab_stats = gr.Tab(t_init.get("tab_stats", ""))
                with ui_tab_stats:
                    ui_stats_status = gr.Markdown()
                    with gr.Row():
                        with gr.Column(scale=1):
                            ui_stats_table = gr.Dataframe(headers=t_init.get("stat_df_headers", []), interactive=True, type="pandas", row_count=(1, "dynamic"), elem_id="stats_table")
                            ui_btn_civitai = gr.Button(t_init.get("btn_civitai", ""), variant="secondary")
                            ui_civitai_output = gr.Textbox(label="Format", interactive=False, lines=5)
                            with gr.Row():
                                ui_btn_top20 = gr.Button(t_init.get("btn_top20", ""))
                                ui_btn_orph = gr.Button(t_init.get("btn_orph", ""))
                            ui_txt_orph = gr.Textbox(label=t_init.get("txt_orph", ""), lines=4)
                        with gr.Column(scale=2):
                            pie_chart = gr.Plot(label="Graphique (Répartition)")
                            bar_chart = gr.Plot(label="Graphique (Occurrences)")
                            gr.Markdown("---")
                            ui_adv_stats_title = gr.Markdown(t_init.get("adv_stats_title", ""))
                            btn_calc_adv = gr.Button(t_init.get("btn_calc_adv", ""), variant="primary")
                            with gr.Row():
                                plot_heatmap = gr.Plot(label="Matrice")
                                plot_bucket = gr.Plot(label="Résolutions")
                            with gr.Row():
                                with gr.Column():
                                    txt_anti = gr.Textbox(label=t_init.get("anti_title", ""), lines=6, interactive=False)
                                with gr.Column():
                                    txt_contra = gr.Textbox(label=t_init.get("contra_title", ""), lines=6, interactive=False)

        with gr.Column(scale=0, elem_id="right_panel"):
            ui_lib_title = gr.HTML(t_init.get("lib_title", ""))
            
            _lmc = t_init.get("lib_mode_choices", ["Add", "Remove", "Replace"])
            ui_lib_mode = gr.Radio(
                choices=[(_lmc[0], LIB_MODE_ADD), (_lmc[1], LIB_MODE_REMOVE), (_lmc[2], LIB_MODE_REPLACE)],
                label=t_init.get("lib_mode", ""),
                value=LIB_MODE_ADD,
            )
            ui_lib_target = gr.Textbox(label=t_init.get("lib_target_rem", ""), placeholder="Ex: 1girl", visible=False)
            
            ui_btn_apply_lib = gr.Button(t_init.get("btn_apply_lib_add", ""), variant="primary")
            
            gr.Markdown("---")
            ui_lib_add_text = gr.Textbox(show_label=False, lines=3, placeholder=t_init.get("lib_add_text_ph", ""))
            ui_btn_add_to_lib = gr.Button(t_init.get("btn_add_to_lib", ""), size="sm")
            
            with gr.Row():
                ui_btn_uncheck_all = gr.Button(t_init.get("btn_uncheck_all", ""), size="sm")
                ui_btn_clear_lib = gr.Button(t_init.get("btn_clear_lib", ""), variant="stop", size="sm")
            
            gr.Markdown("---")
            ui_lib_list_title = gr.Markdown(t_init.get("lib_list_title", ""))
            
            ui_lib_html = gr.HTML(render_lib_html([], "FR"))

# ==========================================
# CÂBLAGE DES ÉVÉNEMENTS
# ==========================================

    def update_lib_ui(mode, lang):
        t = UI_T.get(lang, UI_T.get("FR", {}))
        if mode == LIB_MODE_ADD:
            return gr.update(visible=False), gr.update(value=t.get("btn_apply_lib_add", ""))
        elif mode == LIB_MODE_REMOVE:
            return gr.update(visible=True, label=t.get("lib_target_rem", "")), gr.update(value=t.get("btn_apply_lib_rem", ""))
        else:
            return gr.update(visible=True, label=t.get("lib_target_rep", "")), gr.update(value=t.get("btn_apply_lib_rep", ""))

    ui_lib_mode.change(fn=update_lib_ui, inputs=[ui_lib_mode, lang_radio], outputs=[ui_lib_target, ui_btn_apply_lib])

    ui_multi_select_cb.change(fn=lambda x: x, inputs=[ui_multi_select_cb], outputs=[])
    js_toggle = "function() { const p = document.getElementById('left_panel'); const b = document.getElementById('toggle_gallery_btn'); if (p.classList.contains('collapsed')) { p.classList.remove('collapsed'); b.innerText = '◀'; } else { p.classList.add('collapsed'); b.innerText = '▶'; } return []; }"
    ui_toggle_panel_btn.click(fn=None, js=js_toggle)
    ui_browse_btn.click(fn=browse_folder, inputs=[], outputs=[dir_input])
    ui_gallery_cols.change(fn=lambda x: gr.update(columns=int(x)), inputs=[ui_gallery_cols], outputs=[gallery])

    ui_load_btn.click(fn=load_dataset, inputs=[dir_input, ui_sort_order, lang_radio], outputs=[dataset_state, filtered_state, history_state, ui_status_text, gallery, selected_indices_state, ui_selection_status, ui_hidden_sync_input, ui_hidden_tags_input, current_idx_state])
    ui_search_box.change(fn=filter_gallery, inputs=[dataset_state, ui_search_box, ui_sort_order, lang_radio], outputs=[filtered_state, gallery, selected_indices_state, ui_selection_status, ui_hidden_sync_input, current_idx_state])
    ui_sort_order.change(fn=filter_gallery, inputs=[dataset_state, ui_search_box, ui_sort_order, lang_radio], outputs=[filtered_state, gallery, selected_indices_state, ui_selection_status, ui_hidden_sync_input, current_idx_state])
    
    ui_hidden_sync_btn.click(fn=handle_sync, inputs=[ui_hidden_sync_input, dataset_state, filtered_state, current_idx_state, current_caption, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, selected_indices_state, ui_selection_status, current_img, highlight_preview, current_caption, word_counter, current_idx_state, ui_viewer_status, ui_hidden_tags_input])
    ui_btn_prev.click(fn=nav_prev, inputs=[dataset_state, filtered_state, current_idx_state, current_caption, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, current_img, highlight_preview, current_caption, word_counter, current_idx_state, ui_viewer_status])
    ui_btn_next.click(fn=nav_next, inputs=[dataset_state, filtered_state, current_idx_state, current_caption, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, current_img, highlight_preview, current_caption, word_counter, current_idx_state, ui_viewer_status])
    ui_save_single_btn.click(fn=save_single_caption, inputs=[dataset_state, filtered_state, current_idx_state, current_caption, lang_radio], outputs=[dataset_state, filtered_state, ui_single_save_status])
    ui_clear_sel_btn.click(fn=clear_selection, inputs=[lang_radio], outputs=[selected_indices_state, ui_selection_status, ui_hidden_sync_input])

    current_caption.change(fn=do_live_translation, inputs=[current_caption, ui_trans_engine, ui_trans_target, api_backend, api_url_input, llm_model, lang_radio], outputs=[ui_live_translation_output], show_progress="hidden")
    
    ui_btn_translate_entire_caption.click(
        fn=translate_entire_caption_action, 
        inputs=[dataset_state, filtered_state, current_idx_state, current_caption, ui_trans_engine, ui_trans_source, api_backend, api_url_input, llm_model, ui_tracked_words, lang_radio], 
        outputs=[dataset_state, filtered_state, current_caption, highlight_preview, word_counter, ui_single_save_status]
    )
    ui_btn_insert_trans.click(fn=trans_insert, inputs=[ui_trans_input, current_caption, ui_trans_engine, ui_trans_source, api_backend, api_url_input, llm_model, lang_radio], outputs=[current_caption]).success(fn=lambda: "", outputs=[ui_trans_input])

    js_confirm_batch = "(...args) => { if (!confirm('⚠️ Appliquer cette modification en masse sur la sélection ? / Apply this mass modification to the selection?')) throw new Error('Annulé.'); return args; }"
    js_confirm_undo = "(...args) => { if (!confirm('⚠️ Annuler la dernière action ? / Undo the last action?')) throw new Error('Annulé.'); return args; }"
    
    ui_btn_add_to_lib.click(fn=add_to_lib_html, inputs=[ui_lib_add_text, lib_state, lang_radio], outputs=[ui_lib_html, lib_state, ui_lib_add_text])
    ui_hidden_lib_toggle_btn.click(fn=toggle_lib_item, inputs=[ui_hidden_lib_toggle_input, lib_state, lang_radio], outputs=[ui_lib_html, lib_state])
    ui_hidden_lib_delete_btn.click(fn=delete_lib_item, inputs=[ui_hidden_lib_delete_input, lib_state, lang_radio], outputs=[ui_lib_html, lib_state])
    ui_btn_uncheck_all.click(fn=uncheck_all_lib, inputs=[lib_state, lang_radio], outputs=[ui_lib_html, lib_state])
    ui_btn_clear_lib.click(fn=clear_lib, inputs=[lang_radio], outputs=[ui_lib_html, lib_state])
    
    ui_btn_apply_lib.click(fn=batch_library_cb, js=js_confirm_batch, inputs=[dataset_state, lib_state, ui_lib_mode, ui_lib_target, selected_indices_state, ui_search_box, current_idx_state, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, history_state, ui_batch_status, ui_preview_table, current_caption, highlight_preview, word_counter, gallery])

    js_get_sel = "function(tracker, dummy) { let sel = window.getSelection().toString().trim(); if(!sel) { let ae = document.activeElement; if(ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT')) sel = ae.value.substring(ae.selectionStart, ae.selectionEnd).trim(); } return [tracker, sel || \"\"]; }"
    ui_hidden_calc_btn.click(fn=analyze_dataset, inputs=[dataset_state, ui_tracked_words, lang_radio], outputs=[pie_chart, bar_chart, ui_stats_table, stats_df_state, ui_export_config_df, config_df_state, ui_stats_status])
    ui_tracked_words.change(fn=update_viewer, inputs=[filtered_state, current_idx_state, ui_tracked_words, lang_radio], outputs=[current_img, highlight_preview, current_caption, word_counter, current_idx_state, ui_viewer_status])
    ui_toggle_tag_btn.click(fn=toggle_tracked_word, inputs=[ui_tracked_words, dummy_selection], outputs=[ui_tracked_words], js=js_get_sel).success(fn=None, js="function(){ setTimeout(()=>document.getElementById('hidden_calc_btn')?.click(), 100); }")
    current_caption.change(fn=update_word_count, inputs=[current_caption, lang_radio], outputs=[word_counter])
    ui_recipes_dropdown.change(fn=apply_recipe, inputs=[ui_recipes_dropdown], outputs=[ui_tracked_words])
    ui_save_recipe_btn.click(fn=save_recipe, inputs=[ui_recipe_name, ui_tracked_words], outputs=[ui_recipes_dropdown, ui_status_text])

    ui_btn_undo.click(fn=undo_last_action, js=js_confirm_undo, inputs=[dataset_state, history_state, current_idx_state, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, ui_batch_status, current_caption, highlight_preview, word_counter])
    ui_btn_clean_com.click(fn=batch_clean_commas, js=js_confirm_batch, inputs=[dataset_state, selected_indices_state, ui_search_box, current_idx_state, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, history_state, ui_batch_status, ui_preview_table, current_caption, highlight_preview, word_counter])
    ui_btn_clean_dup.click(fn=batch_remove_duplicates, js=js_confirm_batch, inputs=[dataset_state, selected_indices_state, ui_search_box, current_idx_state, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, history_state, ui_batch_status, ui_preview_table, current_caption, highlight_preview, word_counter])

    ui_export_config_df.select(fn=get_row_index, inputs=[config_df_state], outputs=[recipe_selected_row, ui_quick_prio, ui_quick_target])
    ui_quick_prio.change(fn=apply_quick_prio, inputs=[ui_quick_prio, recipe_selected_row, config_df_state], outputs=[ui_export_config_df, config_df_state, ui_tracked_words, recipe_selected_row])
    ui_quick_target.change(fn=apply_quick_target, inputs=[ui_quick_target, recipe_selected_row, config_df_state], outputs=[ui_export_config_df, config_df_state, ui_tracked_words])
    ui_btn_up.click(fn=df_move_up, inputs=[ui_export_config_df, recipe_selected_row], outputs=[ui_export_config_df, recipe_selected_row, ui_tracked_words])
    ui_btn_down.click(fn=df_move_down, inputs=[ui_export_config_df, recipe_selected_row], outputs=[ui_export_config_df, recipe_selected_row, ui_tracked_words])
    ui_btn_del.click(fn=df_delete_row, inputs=[ui_export_config_df, recipe_selected_row], outputs=[ui_export_config_df, recipe_selected_row, ui_tracked_words])
    ui_hidden_dnd_btn.click(fn=handle_drag_and_drop, inputs=[ui_hidden_dnd_input, ui_export_config_df], outputs=[ui_export_config_df, ui_tracked_words])
    ui_export_config_df.change(fn=handle_recipe_df_safe, inputs=[ui_export_config_df, config_df_state, ui_tracked_words], outputs=[ui_export_config_df, config_df_state, ui_tracked_words])

    ui_btn_civitai.click(fn=generate_civitai_format, inputs=[ui_stats_table], outputs=[ui_civitai_output])
    ui_btn_top20.click(fn=auto_fill_top_tags, inputs=[dataset_state], outputs=[ui_tracked_words]).success(fn=None, js="function(){ setTimeout(()=>document.getElementById('hidden_calc_btn')?.click(), 100); }")
    ui_btn_orph.click(fn=find_orphans, inputs=[dataset_state, lang_radio], outputs=[ui_txt_orph])
    ui_stats_table.change(fn=handle_stats_df_safe, inputs=[ui_stats_table, stats_df_state, ui_tracked_words], outputs=[ui_stats_table, stats_df_state, ui_tracked_words]).success(fn=None, js="function(){ setTimeout(()=>document.getElementById('hidden_calc_btn')?.click(), 100); }")
    btn_calc_adv.click(fn=update_advanced_stats, inputs=[dataset_state], outputs=[plot_heatmap, plot_bucket, txt_anti, txt_contra])

    ui_btn_simul.click(fn=simulate_and_export, inputs=[dataset_state, ui_export_dir, ui_export_config_df, gr.State(True), selected_indices_state, ui_strategy_radio, ui_max_img_input, lang_radio], outputs=[ui_export_status, export_gallery, export_pie, bar_chart])
    ui_btn_exp.click(fn=simulate_and_export, inputs=[dataset_state, ui_export_dir, ui_export_config_df, gr.State(False), selected_indices_state, ui_strategy_radio, ui_max_img_input, lang_radio], outputs=[ui_export_status, export_gallery, export_pie, bar_chart])
    btn_scan_dups.click(fn=scan_duplicates_advanced, inputs=[dataset_state, ui_hash_tol], outputs=[dup_dropdown, dup_mapping_state])
    dup_dropdown.change(fn=load_duplicate_pair, inputs=[dup_dropdown, dup_mapping_state], outputs=[dup_img_A, dup_img_B, dup_idA, dup_idB])
    btn_del_A.click(fn=delete_duplicate, inputs=[dataset_state, filtered_state, dup_idA, dup_dropdown, dup_mapping_state], outputs=[dataset_state, filtered_state, dup_dropdown, dup_mapping_state, dup_status])
    btn_del_B.click(fn=delete_duplicate, inputs=[dataset_state, filtered_state, dup_idB, dup_dropdown, dup_mapping_state], outputs=[dataset_state, filtered_state, dup_dropdown, dup_mapping_state, dup_status])
    btn_rename.click(fn=batch_rename_dataset, inputs=[dataset_state, ui_rename_prefix], outputs=[dataset_state, prep_status])
    btn_prep.click(fn=batch_process_images, inputs=[dataset_state, prep_dest, prep_size, prep_format, prep_crop, prep_alpha], outputs=[prep_status])

    ai_action_dropdown.change(fn=update_ai_action_desc, inputs=[ai_action_dropdown], outputs=[ai_action_desc, custom_prompt_group, injection_group])
    api_backend.change(
        fn=lambda x: "http://127.0.0.1:11434" if x == BACKEND_OLLAMA else "http://127.0.0.1:1234",
        inputs=[api_backend], outputs=[api_url_input],
    )
    ai_template_dd.change(fn=apply_ai_recipe, inputs=[ai_template_dd], outputs=[custom_prompt_input])
    btn_save_template.click(fn=save_ai_recipe, inputs=[ai_template_name, custom_prompt_input], outputs=[ai_template_dd])
    btn_run_ai.click(fn=process_ai_action, inputs=[dataset_state, selected_indices_state, ui_search_box, ai_action_dropdown, custom_prompt_input, injection_mode, use_vision_for_custom, vlm_model, llm_model, api_backend, api_url_input, ai_temp, ai_ctx, ai_sys, current_idx_state, ui_tracked_words, lang_radio], outputs=[dataset_state, filtered_state, history_state, ai_status, ui_hidden_tags_input, current_caption, highlight_preview, word_counter])
    btn_bias.click(fn=analyze_bias, inputs=[dataset_state, llm_model, api_backend, api_url_input, ai_temp, ai_ctx, ai_sys], outputs=[txt_bias])

    app.load(fn=lambda: None, inputs=None, outputs=None, js=custom_js)

def _cli_entry():
    # CSS is already attached at gr.Blocks(css=...). Launch should not re-pass it.
    app.launch(inbrowser=True, server_name="127.0.0.1")


if __name__ == "__main__":
    _cli_entry()