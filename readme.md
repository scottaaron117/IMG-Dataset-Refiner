# **📊 IMG Dataset Refiner (v4.0 Pro) — scottaaron117 fork**

> **Fork notice.** This is a maintenance fork of [NyxAwroo/IMG-Dataset-Refiner](https://github.com/NyxAwroo/IMG-Dataset-Refiner).
> Original concept, features, and UI by **NyxAwroo** — all credit for the design goes upstream.
> This fork focuses on making it installable on current Python + Gradio 5.x and on cleaning up architectural fragility. See **What's changed in the fork** below.

![English](https://img.shields.io/badge/Language-English-blue?style=flat-square) ![Français](https://img.shields.io/badge/Langue-Fran%C3%A7ais-blue?style=flat-square)

<div align="center">
  <img src="https://github.com/NyxAwroo/IMG-Dataset-Refiner/raw/main/logotype/logo.jpg" alt="IMG Dataset Refiner Logo" width="250"/>
</div>

**The ultimate tool for management, balancing, pre-processing, batch editing, and AI assistance (VLM/LLM) for model training preparation (LoRA, SDXL, Flux, etc...)** [Installation](#bookmark=id.1cp2sfue8mje) • [What's new in v4.0](#bookmark=id.orop7sxzzoky) • [Features](#bookmark=id.o5ybkqotgy38) • [Workflow](#bookmark=id.rwtjzpocgan2)

## **🎯 About**

**IMG Dataset Refiner** is a "desktop-like" software suite designed for AI model creators. Powered by **Gradio** with native JavaScript injections and custom CSS for optimal performance, this tool allows you to **visualize, massively edit, pre-process, clean, analyze via AI, and export** your image datasets with surgical precision.

**The ultimate tool for management, balancing, pre-processing, and AI assistance (VLM/LLM) for model training preparation (LoRA, SDXL, Flux)** [Installation](#bookmark=id.93ne4h8eoc6q) • [What's new in v3](#bookmark=id.uer02e3me5fz) • [Features](#bookmark=id.4b2b3rabed25) • [Workflow](#bookmark=id.o7c1e8yukqn)

<img src="https://github.com/NyxAwroo/IMG-Dataset-Refiner/blob/main/screenshots%20demo/v4/1.png?raw=true" alt="Aperçu IMG Dataset Refiner v4.0" width="100%">

## **🚀 What's New in v4.0 Pro**

This version brings unprecedented fluidity to the manual editing of your dataset:

* **📚 Word Library (Custom Mass Batch):** A unique, interactive new module to keep a list of tags handy. Check them to Add, Remove, or Replace massively on a selection of images with a single click.  
* **🌍 Live Translation Assistant:** Translate your captions in real-time, inject translated words on the fly, or convert an entire .txt file to English instantly thanks to deep-translator integration. The preview is displayed live right below your typing area.  
* **⌨️ Absolute Productivity:** Navigate from image to image using PageUp/PageDown without ever having to click outside the text box. Save on the fly with Ctrl+S.  
* **🗂️ Dynamic Sorting and Redesigned UI:** Sort your images from A to Z or Z to A, enjoy an interface freed from distracting native menus, and switch the entire application between French and English with a single click.

## **⚙️ Key Features**

### **🤖 AI Capabilities (Local Assistant via API)**

* **Ollama / LM Studio Integration:** Native support to run language models (LLM) and vision models (VLM) directly on the dataset via local API.  
* **Auto-Tagging / Super OCR (VLM):** Full caption generation or precise extraction of text embedded in the image.  
* **Reality Check & Hallucination Hunter (VLM):** The AI compares the text to the image and automatically removes tags that describe invisible elements.  
* **Concept Isolator (VLM):** The AI describes the environment and ignores the central subject, ideal for preparing training data for character LoRAs.  
* **Visual Translator (Booru ↔ Natural):** Intelligent conversion of tag lists into fluid, complete sentences (optimized for Flux and SD3).

### **🖼️ Duplicate Tracking & Pre-processing**

* **Duplicates (ImageHash):** Customizable visual scanner detecting similar images (exact clones or crops) with a quick A/B deletion interface.  
* **Smart Face Crop (OpenCV):** Automatic cropping centered on detected faces to optimize portraits.  
* **Mass Resizing:** High-quality downscaling (Lanczos) to 512, 768, 1024, or 1536px, with automatic handling of transparent PNGs (white background).  
* **Batch Renaming:** Clean, incremental renaming (prefix\_0001.jpg) of all images and their associated .txt files in one click.

### **🧬 Advanced Analytics & Quality**

* **Co-occurrence Matrix (Heatmap):** Interactive Plotly chart analyzing the links between your top 20 tags to detect "Concept Bleeding".  
* **Resolution Bucketing:** Scatter plot chart to visualize the resolution distribution of your raw images.  
* **Contradiction Hunter:** Automatic detection of logical aberrations in your captions (e.g., "day" \+ "night" on the same image).  
* **Orphan Tags:** Detection of unique keywords (often indicative of typos).

<img src="https://github.com/NyxAwroo/IMG-Dataset-Refiner/blob/main/screenshots%20demo/v4/2.png" alt="Aperçu IMG Dataset Refiner v4.0" width="20%">

### **📁 Strategic Export**

* **Auto Balancing (Percentages):** Set appearance targets for your concepts (e.g., 50% man, 50% woman) and the "Greedy" algorithm will pick the perfect images to reach this ratio.  
* **CivitAI Table Generation:** Export your statistics with one click to paste them directly onto your model page.

<img src="https://raw.githubusercontent.com/NyxAwroo/IMG-Dataset-Refiner/refs/heads/main/screenshots%20demo/v4/3.png" alt="Aperçu IMG Dataset Refiner v4.0" width="20%">

## **🔄 Recommended Workflow**

1️⃣ **Pre-processing (🖼️ Tab)** └─ Clean visual duplicates, appropriately rename your files, and resize your images if necessary.  
2️⃣ **AI Auto-Captioning (🤖 Tab)** └─ Let your local Vision model (e.g., LLaVA or Qwen) generate a solid first base of tags on your entire selection.  
3️⃣ **Quick Editing & Translation (👁️ Tab)** └─ Navigate quickly with the keyboard (PageUp/PageDown). Use the **Live Translation** preview to write your ideas in your native language and insert them instantly in English.  
4️⃣ **Mass Editing (⚡ Tab & 📚 Library)** └─ Fill your Custom Library with keywords. Select multiple images (Ctrl+Click), then add or remove these concepts in one click to standardize your dataset.  
5️⃣ **Audits & Strategic Export (📈 & 📁 Tabs)** └─ Ensure there is no bias using the co-occurrence *Heatmap*. Enter your % targets, simulate the balance, and export a perfect, training-ready dataset\!

## **⚙️ Installation**

Requires **Python 3.10, 3.11, or 3.12**. Gradio 5.x dropped support for Python 3.9.

```
git clone https://github.com/scottaaron117/IMG-Dataset-Refiner.git
cd IMG-Dataset-Refiner
pip install -e .          # preferred; uses pyproject.toml
# or:
pip install -r requirements.txt
python lora_manager.py
```

> **Why pinned?** The original `requirements.txt` only floor-pinned Gradio, which caused two startup crashes on current pip installs: `huggingface_hub` 1.x removed `HfFolder`, and Gradio 6 renamed `col_count` → `column_count`. The fork pins `gradio>=5.15,<6` and `huggingface_hub<1.0` to avoid both.

> **Folder picker.** The upstream "Browse" button opened a tkinter dialog on the *server* — wrong for a web app, broken on remote/headless installs, and an `ImportError` on bare Linux. The fork replaces it with a notice prompting you to paste the path. The textbox accepts Windows paths (`D:\my-dataset`) directly.

## **🔧 What's changed in the fork**

**Phase 1 — Installable on Gradio 5.x**
- Real `pyproject.toml` with all deps pinned. `pip install -e .` works on Python 3.10/3.11/3.12.
- Fixed two startup-crash bugs: `huggingface_hub` 1.x removed `HfFolder` (pinned `<1.0`); Gradio 6 renamed `col_count` to `column_count` but upstream wrote `column_count` against an installed Gradio 5 — pinned `gradio>=5.15,<6` and renamed back to `col_count`.
- Fixed malformed `row_count=("dynamic")` (was the string `"dynamic"`, not a tuple).
- Removed the redundant `app.launch(css=...)` that raised `TypeError` on every Gradio 5 launch.
- Removed the server-side tkinter "Browse" dialog (focus-stealing in a web app, `ImportError` on bare Linux). Path textbox accepts Windows paths directly.

**Phase 2 — JS bridge repaired for Gradio 5 DOM**
- Gradio 5 renders gallery thumbnails as `<a class="thumbnail-item">`, not `<button>`. Every `#main_gallery button` selector was silently matching nothing — that's why selection didn't work. Replaced with `#main_gallery .thumbnail-item` (with the old selector kept as fallback for older Gradio).
- `.gradio-dataframe` class no longer exists in Gradio 5. Added stable `elem_id`s to the three Dataframes and rewrote the CSS and drag-row selectors against them.
- Scoped the two `MutationObserver`s from `document.body, subtree:true` (firing on every keystroke) down to the specific containers they actually care about.
- Replaced a 150ms `setInterval` polling hack with a proper `input` event listener.

**Phase 3 — Cleanup**
- CSS (38 lines) and JavaScript (305 lines) moved out of inline Python strings into `assets/styles.css` and `assets/scripts.js`. Editors get syntax highlighting, diffs are sane.
- **Enum-key control flow.** Three branch sites (`batch_library_cb`, `update_lib_ui`, `simulate_and_export`) compared against the user-visible dropdown label (`"Ajouter" in mode or "Add" in mode`, `strategy in ["Filtre Classique", "Classic Filter", ...]`). Renaming a string in `en.json` would silently change behaviour. Now the dropdowns use Gradio's `choices=[(label, key)]` form, the handlers branch on internal constants (`LIB_MODE_ADD`, `STRAT_CLASSIC`, etc.), and labels are display-only. Same fix applied to `api_backend`.
- Deleted 187 lines of dead code: `change_language()` and its giant `lang_radio.change()` wiring registration. Unreachable since the language radio became invisible; the function also assumed the old plain-string dropdown choices and would have corrupted the new tuple-form radios if it ever fired.
- Headless-Chromium browser smoke test added at `tests/test_smoke.py` — drives the bundled example dataset end-to-end (gallery click / shift-range / ctrl-toggle, autocomplete, enum-key wiring). 24/24 passing.

**File count**: `lora_manager.py` 2,082 → 1,631 lines. CSS+JS extracted to `assets/`. Total app size unchanged; the layout is just no longer a single-file monolith.

See `Changelog.md` for the full per-commit history and the upstream version history.

## **📦 Project Structure**

```
IMG-Dataset-Refiner/
├── lora_manager.py          # Main entry point (UI assembly + business logic)
├── assets/
│   ├── styles.css           # Extracted from inline Python string
│   └── scripts.js           # Extracted from inline Python string
├── tests/
│   └── test_smoke.py        # Playwright headless-Chromium regression test
├── pyproject.toml           # Pinned dependencies (preferred over requirements.txt)
├── requirements.txt         # Mirror of pyproject.toml for pip install -r
├── en.json                  # English UI strings (control-flow uses enum keys, not these)
├── fr.json                  # Upstream French strings (still on disk, unused at runtime)
├── lora_recipes.json        # User export-config saves (auto-created)
├── ai_recipes.json          # User custom AI prompts (auto-created)
├── Changelog.md             # Upstream version history + this fork's commits
├── readme.md                # This file
└── README_fr.md             # Upstream French README (kept for attribution)
```

## **🎓 Use Cases**

✅ Preparation of demanding datasets for **LoRA fine-tuning** (SD 1.5, SDXL, Flux)  
✅ Privacy-respecting **local auto-captioning** (100% offline)  
✅ Mathematical balancing of **multi-concept** datasets  
✅ Lightning-fast mass annotation via the **Custom Library** ✅ Identification and resolution of **overfitting** issues via visual audits

## **📄 License**

Free to use and modify for your personal and professional AI workflows.

## **🤝 Contribution**

Contributions are welcome\! Feel free to:

* Report bugs via Issues  
* Propose improvements  
* Submit Pull Requests

**Forged with ❤️ for the AI community** [⬆️ Back to top](#bookmark=id.jsyvg8l7x16z)
