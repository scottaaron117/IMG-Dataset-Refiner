function() {
    if (window.__DIES_INJECTED) return;
    window.__DIES_INJECTED = true;
    document.body.classList.add('dark');
    window.gallerySelectedIndices = new Set();
    window.lastClickedIndex = -1;
    window.allDatasetTags = [];

    function setNativeValue(element, value) {
        const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        const prototype = Object.getPrototypeOf(element);
        const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
        const setter = descriptor ? descriptor.set : valueSetter;
        setter.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
    }

    window.clickLibToggle = function(idx) {
        let inp = document.querySelector('#hidden_lib_toggle_input textarea');
        if(!inp) inp = document.querySelector('#hidden_lib_toggle_input input');
        if(inp) { setNativeValue(inp, idx.toString() + "_" + Date.now()); }
        setTimeout(() => document.getElementById('hidden_lib_toggle_btn')?.click(), 50);
    };
    
    window.clickLibDelete = function(idx, e) {
        if(e) e.stopPropagation(); 
        let inp = document.querySelector('#hidden_lib_delete_input textarea');
        if(!inp) inp = document.querySelector('#hidden_lib_delete_input input');
        if(inp) { setNativeValue(inp, idx.toString() + "_" + Date.now()); }
        setTimeout(() => document.getElementById('hidden_lib_delete_btn')?.click(), 50);
    };

    // Gradio 5+ renders gallery thumbnails as <a class="thumbnail-item">, not <button>.
    // Keeping `button` as a fallback for older versions.
    var GALLERY_THUMB_SEL = '#main_gallery .thumbnail-item, #main_gallery button';
    function getGalleryThumbs() { return document.querySelectorAll(GALLERY_THUMB_SEL); }
    function updateGalleryVisuals() { getGalleryThumbs().forEach((el, idx) => { el.classList.toggle('custom-selected', window.gallerySelectedIndices.has(idx)); }); }
    function syncWithPython(viewIndex) {
        const payload = { selected: Array.from(window.gallerySelectedIndices), viewIndex: viewIndex };
        const wrapper = document.getElementById('hidden_sync_input');
        const inputEl = wrapper ? wrapper.querySelector('textarea, input') : null;
        if (inputEl) {
            setNativeValue(inputEl, JSON.stringify(payload));
            setTimeout(() => { const btn = document.getElementById('hidden_sync_btn'); if (btn) btn.click(); }, 30);
        }
    }

    function setupAutocomplete() {
        const captionWrappers = document.querySelectorAll('#viewer_caption_area textarea');
        if (captionWrappers.length === 0) return;
        const inp = captionWrappers[0];
        if(inp.dataset.acSetup) return;
        inp.dataset.acSetup = "true";
        let currentFocus;
        inp.addEventListener("input", function(e) {
            let a, b, i, val = this.value; closeAllLists(); if (!val) return false;
            let lastCommaIdx = val.lastIndexOf(','); let currentWord = val.substring(lastCommaIdx + 1).trimStart();
            let prefix = val.substring(0, lastCommaIdx + 1); if(val.length > 0 && val[lastCommaIdx+1] === ' ') prefix += ' ';
            if (currentWord.length < 2) return false;
            currentFocus = -1; a = document.createElement("DIV"); a.setAttribute("id", "autocomplete-list"); this.parentNode.appendChild(a);
            const tagsInput = document.getElementById('hidden_tags_input');
            if(tagsInput) { const rawTags = tagsInput.querySelector('textarea, input')?.value || ""; if(rawTags) window.allDatasetTags = rawTags.split('|'); }
            let matches = 0;
            for (i = 0; i < window.allDatasetTags.length; i++) {
                if (window.allDatasetTags[i].toLowerCase().includes(currentWord.toLowerCase())) {
                    matches++; if(matches > 10) break;
                    b = document.createElement("DIV");
                    let matchIdx = window.allDatasetTags[i].toLowerCase().indexOf(currentWord.toLowerCase());
                    let highlighted = window.allDatasetTags[i].substring(0, matchIdx) + "<strong>" + window.allDatasetTags[i].substring(matchIdx, matchIdx + currentWord.length) + "</strong>" + window.allDatasetTags[i].substring(matchIdx + currentWord.length);
                    b.innerHTML = highlighted; b.innerHTML += "<input type='hidden' value='" + window.allDatasetTags[i] + "'>";
                    b.addEventListener("click", function(e) { inp.value = prefix + this.getElementsByTagName("input")[0].value + ", "; inp.dispatchEvent(new Event('input', { bubbles: true })); closeAllLists(); });
                    a.appendChild(b);
                }
            }
        });
        inp.addEventListener("keydown", function(e) {
            let x = document.getElementById("autocomplete-list"); if (x) x = x.getElementsByTagName("div");
            if (e.keyCode == 40) { currentFocus++; addActive(x); } else if (e.keyCode == 38) { currentFocus--; addActive(x); }
            else if (e.keyCode == 13 || e.keyCode == 9) { if (currentFocus > -1 && x) { e.preventDefault(); x[currentFocus].click(); } }
        });
        function addActive(x) { if (!x) return false; removeActive(x); if (currentFocus >= x.length) currentFocus = 0; if (currentFocus < 0) currentFocus = (x.length - 1); x[currentFocus].classList.add("autocomplete-active"); }
        function removeActive(x) { for (var i = 0; i < x.length; i++) x[i].classList.remove("autocomplete-active"); }
        function closeAllLists(elmnt) { var x = document.getElementsByClassName("autocomplete-list"); for (var i = 0; i < x.length; i++) { if (elmnt != x[i] && elmnt != inp) x[i].parentNode.removeChild(x[i]); } let list = document.getElementById("autocomplete-list"); if(list) list.remove(); }
        document.addEventListener("click", function (e) { closeAllLists(e.target); });
    }

    // Scoped observers — document.body subtree:true was firing on every keystroke.
    // Watch only the regions that actually need re-binding.
    function attachObservers() {
        const gallery = document.getElementById('main_gallery');
        const captionWrap = document.getElementById('viewer_caption_area');
        const tracked = document.getElementById('tracked_words_input');
        const exportDf = document.getElementById('export_config_df');
        const statsDf = document.getElementById('stats_table');

        if (gallery && !gallery.dataset.obsAttached) {
            gallery.dataset.obsAttached = 'true';
            new MutationObserver(updateGalleryVisuals).observe(gallery, { childList: true, subtree: true });
        }
        if (captionWrap && !captionWrap.dataset.obsAttached) {
            captionWrap.dataset.obsAttached = 'true';
            new MutationObserver(setupAutocomplete).observe(captionWrap, { childList: true, subtree: true });
            setupAutocomplete();
        }
        if (tracked) {
            const trackedInput = tracked.querySelector('textarea');
            if (trackedInput && !trackedInput.dataset.commaListener) {
                trackedInput.dataset.commaListener = "true";
                trackedInput.addEventListener('keyup', function(e) { if (e.key === ',' || e.key === 'Enter') { setTimeout(() => document.getElementById('hidden_calc_btn')?.click(), 50); } });
                trackedInput.addEventListener('blur', function(e) { setTimeout(() => document.getElementById('hidden_calc_btn')?.click(), 50); });
            }
        }
        // Auto-select dataframe input on edit, for both export and stats tables.
        [exportDf, statsDf].forEach(root => {
            if (!root || root.dataset.dfInputObsAttached) return;
            root.dataset.dfInputObsAttached = 'true';
            new MutationObserver((mutations) => {
                mutations.forEach(m => m.addedNodes.forEach(node => {
                    if (node.nodeType !== 1) return;
                    const input = node.tagName === 'INPUT' ? node : node.querySelector('input');
                    if (input) {
                        let tries = 0;
                        const selectInterval = setInterval(() => { input.select(); if (tries++ > 15) clearInterval(selectInterval); }, 20);
                    }
                }));
            }).observe(root, { childList: true, subtree: true });
        });

        // Initial visual sync in case the gallery is already populated.
        updateGalleryVisuals();
    }

    // Wait briefly for Gradio to mount, then attach. Retry a few times in case
    // sub-trees load lazily (tabs are mounted on first activation).
    let attachTries = 0;
    const attachInterval = setInterval(() => {
        attachObservers();
        attachTries++;
        if (attachTries > 30) clearInterval(attachInterval); // ~6s of retries
    }, 200);

    // Was `.gradio-dataframe tbody tr` — Gradio 5 dropped that class.
    var DF_ROW_SEL = '#export_config_df tbody tr, #stats_table tbody tr';
    let dragStartIndex = -1;
    document.addEventListener('mousedown', function(e) {
        const tr = e.target.closest(DF_ROW_SEL);
        if (!tr) return;
        if (e.target.closest('input') || e.target.closest('textarea')) { tr.removeAttribute('draggable'); }
        else { tr.setAttribute('draggable', 'true'); }
    });

    document.addEventListener('dragstart', function(e) {
        const tr = e.target.closest('tbody tr[draggable="true"]');
        if (tr) {
            dragStartIndex = Array.from(tr.parentNode.children).indexOf(tr);
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', dragStartIndex);
            setTimeout(() => tr.classList.add('dragging'), 0);
        }
    });

    document.addEventListener('dragover', function(e) {
        const draggingTr = document.querySelector('.dragging');
        const tr = e.target.closest('tbody tr');
        if (tr && draggingTr && tr !== draggingTr && tr.parentNode === draggingTr.parentNode) {
            e.preventDefault(); 
            const rect = tr.getBoundingClientRect();
            const mid = rect.top + rect.height / 2;
            if (e.clientY < mid) { tr.before(draggingTr); } else { tr.after(draggingTr); }
        }
    });

    document.addEventListener('dragend', function(e) {
        const tr = e.target.closest('tbody tr');
        if (tr) { tr.classList.remove('dragging'); tr.removeAttribute('draggable'); }
    });

    document.addEventListener('drop', function(e) {
        const tr = e.target.closest('tbody tr');
        if (tr) {
            e.preventDefault();
            const draggingTr = document.querySelector('.dragging');
            if(draggingTr) { draggingTr.classList.remove('dragging'); draggingTr.removeAttribute('draggable'); }
            
            const dragEndIndex = Array.from(tr.parentNode.children).indexOf(tr);
            if (dragStartIndex !== -1 && dragStartIndex !== dragEndIndex) {
                const wrapper = document.getElementById('hidden_dnd_input');
                const hiddenInput = wrapper ? wrapper.querySelector('textarea, input') : null;
                const hiddenBtn = document.getElementById('hidden_dnd_btn');
                if (hiddenInput && hiddenBtn) {
                    setNativeValue(hiddenInput, dragStartIndex + "," + dragEndIndex);
                    setTimeout(() => hiddenBtn.click(), 50);
                }
            }
        }
        dragStartIndex = -1;
    });

    window.addEventListener('keydown', function(e) {
        const tag = e.target.tagName.toLowerCase();
        const isInput = (tag === 'input' || tag === 'textarea');

        if (e.altKey && e.code === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); document.getElementById('btn_move_up')?.click(); return; }
        if (e.altKey && e.code === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); document.getElementById('btn_move_down')?.click(); return; }
        if (isInput && !e.altKey && !e.ctrlKey && !e.metaKey && e.code !== 'PageUp' && e.code !== 'PageDown') return;

        if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyA' || e.key.toLowerCase() === 'a')) {
            if (isInput) return;
            e.preventDefault(); e.stopPropagation();
            const btns = getGalleryThumbs();
            window.gallerySelectedIndices.clear();
            btns.forEach((b, i) => window.gallerySelectedIndices.add(i));
            updateGalleryVisuals();
            syncWithPython(window.lastClickedIndex !== -1 ? window.lastClickedIndex : 0);
            return;
        }

        if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyF' || e.key.toLowerCase() === 'f')) { e.preventDefault(); e.stopPropagation(); const searchBox = document.querySelector('input[placeholder*="mot"], input[placeholder*="word"]'); if (searchBox) { searchBox.focus(); searchBox.select(); } return; }
        if (e.altKey && (e.code === 'KeyS' || e.key.toLowerCase() === 's')) { e.preventDefault(); e.stopPropagation(); document.getElementById('toggle_tag_btn')?.click(); return; }
        if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyS' || e.key.toLowerCase() === 's')) { e.preventDefault(); e.stopPropagation(); document.getElementById('save_single_btn')?.click(); return; }
        if (e.altKey && (e.code === 'KeyC' || e.key.toLowerCase() === 'c')) { e.preventDefault(); e.stopPropagation(); document.getElementById('clear_sel_btn')?.click(); return; }
        
        if (e.code === 'PageUp') { e.preventDefault(); document.getElementById('prev_btn')?.click(); return; }
        if (e.code === 'PageDown') { e.preventDefault(); document.getElementById('next_btn')?.click(); return; }
        if (isInput) return;
        if (e.code === 'ArrowLeft' || e.key === 'ArrowLeft') { e.preventDefault(); document.getElementById('prev_btn')?.click(); }
        if (e.code === 'ArrowRight' || e.key === 'ArrowRight') { e.preventDefault(); document.getElementById('next_btn')?.click(); }
    }, true); 

    document.addEventListener('click', function(e) {
        // --- 1. ÉCOUTE DES CLICS DE LA BIBLIOTHÈQUE ---
        const delBtn = e.target.closest('.lib-item-delete');
        if (delBtn) {
            e.preventDefault(); e.stopPropagation();
            const idx = delBtn.getAttribute('data-idx');
            if (idx !== null) window.clickLibDelete(idx, e);
            return;
        }

        const libItem = e.target.closest('.lib-item-custom');
        if (libItem) {
            e.preventDefault(); e.stopPropagation();
            const idx = libItem.getAttribute('data-idx');
            if (idx !== null) window.clickLibToggle(idx);
            return;
        }

        // --- 2. Gallery click handling ---
        if (e.target.closest('label') || e.target.tagName === 'INPUT') return;
        const btn = e.target.closest(GALLERY_THUMB_SEL);
        if (!btn) return;

        e.preventDefault(); e.stopPropagation();
        const btns = Array.from(getGalleryThumbs());
        const index = btns.indexOf(btn);
        if (index === -1) return;

        const cbWrapper = document.getElementById('multi_cb');
        const isMultiChecked = cbWrapper ? (cbWrapper.querySelector('input[type="checkbox"]')?.checked || false) : false;

        if (e.shiftKey && window.lastClickedIndex !== -1) {
            const start = Math.min(window.lastClickedIndex, index);
            const end = Math.max(window.lastClickedIndex, index);
            if (!e.ctrlKey && !e.metaKey && !isMultiChecked) { window.gallerySelectedIndices.clear(); }
            for (let i = start; i <= end; i++) window.gallerySelectedIndices.add(i);
        } 
        else if (e.ctrlKey || e.metaKey || isMultiChecked) {
            if (window.gallerySelectedIndices.has(index)) window.gallerySelectedIndices.delete(index);
            else window.gallerySelectedIndices.add(index);
        } 
        else {
            window.gallerySelectedIndices.clear();
            window.gallerySelectedIndices.add(index); 
        }

        window.lastClickedIndex = index;
        updateGalleryVisuals();
        syncWithPython(index);
    }, true);

    // Listen for Python-side clears: clear_selection() writes "{}" into
    // hidden_sync_input. Watch the textarea's 'input' event instead of polling.
    function bindClearListener() {
        const wrapper = document.getElementById('hidden_sync_input');
        const selInput = wrapper ? wrapper.querySelector('textarea, input') : null;
        if (!selInput || selInput.dataset.clearListener) return;
        selInput.dataset.clearListener = 'true';
        selInput.addEventListener('input', function() {
            if (selInput.value === '{}' && window.gallerySelectedIndices.size > 0) {
                window.gallerySelectedIndices.clear();
                updateGalleryVisuals();
            }
        });
    }
    // Initial attempt + retry (hidden_sync_input is mounted with the rest of
    // the Blocks; attach as soon as it appears).
    let clearTries = 0;
    const clearBindHandle = setInterval(() => {
        bindClearListener();
        if (++clearTries > 30 || document.getElementById('hidden_sync_input')?.querySelector('textarea, input')?.dataset.clearListener) {
            clearInterval(clearBindHandle);
        }
    }, 200);
}
