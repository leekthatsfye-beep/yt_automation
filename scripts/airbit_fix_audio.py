"""Inspect / fix the audio file attached to an existing Airbit listing.

Usage:
  python scripts/airbit_fix_audio.py --id 3296733 --inspect
  python scripts/airbit_fix_audio.py --id 3296733 --file beats/h00dr1ch.mp3 --replace
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import airbit_upload as au
from selenium.webdriver.common.by import By


def dump_page(driver):
    print("URL:", driver.current_url)
    print("IFRAMES:", len(driver.find_elements(By.TAG_NAME, "iframe")))
    body = driver.execute_script("return document.body.innerText") or ""
    print("BODY TEXT (first 600):", repr(body[:600]))
    for inp in driver.find_elements(By.CSS_SELECTOR, "input, textarea, select"):
        print("INPUT: type=%r name=%r id=%r ph=%r val=%r" % (
            inp.get_attribute("type"), inp.get_attribute("name"),
            inp.get_attribute("id"), inp.get_attribute("placeholder"),
            (inp.get_attribute("value") or "")[:40]))
    for fi in driver.find_elements(By.CSS_SELECTOR, "input[type='file']"):
        print("FILE INPUT: name=%r accept=%r id=%r visible=%s" % (
            fi.get_attribute("name"), fi.get_attribute("accept"),
            fi.get_attribute("id"), fi.is_displayed()))
    for b in driver.find_elements(By.CSS_SELECTOR, "button, a.btn, input[type='submit']"):
        txt = (b.text or b.get_attribute("value") or "").strip()
        if txt:
            print("BUTTON: %r  class=%r" % (txt[:60], (b.get_attribute("class") or "")[:60]))
    name_el = driver.find_elements(By.CSS_SELECTOR, "input[name='name']")
    if name_el:
        print("NAME FIELD value:", repr(name_el[0].get_attribute("value")))
    # any element mentioning the attached file
    for el in driver.find_elements(By.XPATH, "//*[contains(text(), '.mp3') or contains(text(), '.wav')]"):
        t = (el.text or "").strip()
        if t and len(t) < 120:
            print("FILE REF TEXT:", repr(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", default=None,
                    help="listing name to set (save-top / rename)")
    ap.add_argument("--key", default=None,
                    help="key to select on save-top (e.g. 'C maj')")
    ap.add_argument("--stem", default="h00dr1ch",
                    help="normalized beat name fragment to match (default h00dr1ch)")
    ap.add_argument("--file")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--row-html", action="store_true",
                    help="dump the management-list row HTML for the beat")
    ap.add_argument("--drafts", action="store_true",
                    help="dump the stale rows sitting in the create-form upload queue")
    ap.add_argument("--save-top", action="store_true",
                    help="fill required fields on queue row 0 (must be h00dr1ch), save, and dump the response")
    ap.add_argument("--unpublish", action="store_true",
                    help="hide the listing from the store (uncheck is_public and save); reversible")
    ap.add_argument("--rename", type=str, default=None,
                    help="set a new listing name (used to mark the broken listing)")
    ap.add_argument("--bpm", type=str, default=None,
                    help="set the listing BPM (edit page)")
    ap.add_argument("--artwork", type=str, default=None,
                    help="upload a new cover image on the edit page")
    ap.add_argument("--tags", type=str, default=None,
                    help="comma-separated tags to add on the edit page")
    args = ap.parse_args()

    driver = au.launch_browser()
    try:
        if not au.ensure_logged_in(driver):
            print("[FAIL] not logged in")
            return 1
        if args.save_top:
            from selenium.webdriver.support.ui import Select
            driver.get("https://app.airbit.com/beats/create")
            time.sleep(12)
            au.dismiss_cookie_banner(driver)
            driver.execute_script(
                'var el = document.querySelector(\'[data-choice="new"]\');'
                'if (el) el.click();')
            time.sleep(4)
            prefill = driver.execute_script(
                "const i = document.querySelector(\"input[name='beats[0][name]']\");"
                "return i ? i.value : null;")
            print("[+] row 0 prefill:", repr(prefill))
            if not prefill or args.stem.replace("_","").lower() not in prefill.lower().replace(" ", "").replace("_",""):
                print(f"[FAIL] row 0 is not {args.stem} — refusing to fill/save")
                return 1
            name_el = driver.find_element(By.CSS_SELECTOR, "input[name='beats[0][name]']")
            au.safe_type(driver, name_el, args.name or "H00DR1CH !")
            bpm_el = driver.find_element(By.CSS_SELECTOR, "input[name='beats[0][bpm]']")
            au.safe_type(driver, bpm_el, args.bpm or "148")
            Select(driver.find_element(By.CSS_SELECTOR, "select[name='beats[0][genre]']")) \
                .select_by_visible_text("Trap")
            try:
                key_sel = Select(driver.find_element(By.CSS_SELECTOR, "select[name='beats[0][key]']"))
                for opt in key_sel.options:
                    if opt.text.strip().lower() == (args.key or "f maj").lower():
                        key_sel.select_by_visible_text(opt.text)
                        break
            except Exception as e:
                print("[WARN] key:", e)
            print("[+] fields filled; clicking Save")
            btn = au.find_button_by_text(driver, ["Save", "Publish", "Submit"])
            if not btn:
                print("[FAIL] no save button")
                return 1
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            time.sleep(10)
            print("[+] post-save URL:", driver.current_url)
            alerts = driver.execute_script("""
                return [...document.querySelectorAll(
                    '.alert, [class*=error], [class*=danger], [class*=toast], [class*=success], .help-block')]
                    .filter(e => e.offsetParent !== null && e.textContent.trim())
                    .map(e => e.className.slice(0,50) + ' :: ' + e.textContent.trim().slice(0,200));
            """)
            print("ALERTS/TOASTS:", *alerts[:15], sep="\n  ")
            body = driver.execute_script("return document.body.innerText") or ""
            print("BODY SNIPPET:", repr(body[:500]))
            # second pass: the page re-rendered into a per-beat detail view.
            # Re-check the name field, then click the row-level Save again.
            vals = driver.execute_script("""
                const out = {};
                for (const n of ['name','bpm','genre','key']) {
                    const el = document.querySelector(
                        `[name='beats[0][${n}]'], [name='${n}']`);
                    out[n] = el ? el.value : null;
                }
                return out;
            """)
            print("[2nd] current field values:", vals)
            print("[2nd] NOT saving again — first row-Save already published; "
                  "the detail view now shows the NEXT queue row.")
            if False:
                el = driver.find_element(
                    By.CSS_SELECTOR, "[name='beats[0][name]'], [name='name']")
                au.safe_type(driver, el, args.name or "H00DR1CH !")
                print("[2nd] name re-filled")
            print("[2nd] skipping second save (first Save already published row 0)")
            time.sleep(15)
            print("[2nd] URL:", driver.current_url)
            toasts = driver.execute_script("""
                return [...document.querySelectorAll(
                    '.alert, [class*=error], [class*=danger], [class*=toast], [class*=success]')]
                    .filter(e => e.offsetParent !== null && e.textContent.trim())
                    .map(e => e.className.slice(0,40) + ' :: ' + e.textContent.trim().slice(0,150));
            """)
            print("[2nd] TOASTS:", *toasts[:10], sep="\n  ")
            # did the listing land?
            driver.get("https://app.airbit.com/beats")
            time.sleep(8)
            found = ""
            for link in driver.find_elements(By.CSS_SELECTOR, "h4 a[href*='/beats/'][href*='/edit']"):
                if args.stem.replace("_","").lower() in (link.text or "").lower().replace(" ", "").replace("_",""):
                    found = (link.text or "").strip() + " -> " + (link.get_attribute("href") or "")
                    break
            print("[2nd] management list:", found or "H00DR1CH NOT FOUND")
            return 0
        if args.drafts:
            driver.get("https://app.airbit.com/beats/create")
            time.sleep(12)
            au.dismiss_cookie_banner(driver)
            driver.execute_script(
                'var el = document.querySelector(\'[data-choice="new"]\');'
                'if (el) el.click();')
            time.sleep(4)
            rows = driver.execute_script("""
                const names = [...document.querySelectorAll("input[name^='beats[']")]
                    .filter(i => /\\]\\[name\\]$/.test(i.name));
                return names.map(i => i.name + ' = ' + JSON.stringify(i.value));
            """)
            print("DRAFT ROWS (%d):" % len(rows), *rows, sep="\n  ")
            # what does each row's container look like — find remove controls
            ctl = driver.execute_script("""
                const inp = document.querySelector("input[name='beats[0][name]']");
                if (!inp) return 'NO ROW 0';
                const row = inp.closest('.panel, .row, fieldset, div[id], li, tr');
                if (!row) return 'NO CONTAINER';
                const btns = [...row.querySelectorAll('a, button, i, span')]
                    .filter(e => /remove|delete|trash|times|close|fa-x/i.test(
                        (e.className||'') + ' ' + (e.textContent||'').trim()))
                    .map(e => e.tagName + '.' + e.className + ' txt=' + e.textContent.trim().slice(0,20));
                return btns;
            """)
            print("ROW-0 REMOVE CANDIDATES:", ctl)
            return 0
        # find the real edit URL from the beats management list
        driver.get("https://app.airbit.com/beats")
        time.sleep(8)
        au.dismiss_cookie_banner(driver)
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
        url = ""
        row_link = None
        for link in driver.find_elements(By.CSS_SELECTOR, "h4 a[href*='/beats/'][href*='/edit']"):
            txt = (link.text or "").strip().lower()
            if args.stem.replace("_","").lower() in txt.replace(" ", "").replace("_",""):
                url = link.get_attribute("href")
                row_link = link
                print("[+] found beat row: %r -> %s" % (link.text, url))
                break
        if args.unpublish or args.rename or args.bpm or args.artwork or args.tags:
            if not url:
                print("[FAIL] beat row not found")
                return 1
            driver.get(url)
            time.sleep(15)
            if args.rename:
                result = driver.execute_script("""
                    const el = document.querySelector("input[name='name']");
                    if (!el) return 'MISSING';
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, arguments[0]);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return el.value;
                """, args.rename)
                print("[+] name field now: %r" % result)
                if result != args.rename:
                    print("[FAIL] rename did not stick")
                    return 1
            if args.bpm:
                r = driver.execute_script("""
                    const el = document.querySelector("input[name='bpm']");
                    if (!el) return 'MISSING';
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, arguments[0]);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return el.value;
                """, args.bpm)
                print("[+] bpm field now:", r)
            if args.artwork:
                art = Path(args.artwork).resolve()
                if not art.exists():
                    print("[FAIL] artwork file missing:", art)
                    return 1
                el = driver.find_elements(By.CSS_SELECTOR, "input[name='artwork_file']")
                if not el:
                    print("[FAIL] artwork_file input not found")
                    return 1
                driver.execute_script(
                    "arguments[0].style.display='block';"
                    "arguments[0].style.visibility='visible';"
                    "arguments[0].style.opacity='1';"
                    "arguments[0].style.height='auto';"
                    "arguments[0].style.width='auto';", el[0])
                time.sleep(0.3)
                el[0].send_keys(str(art))
                print("[+] artwork sent:", art.name)
                time.sleep(10)
            if args.tags:
                tag_list = [t.strip() for t in args.tags.split(",") if t.strip()][:10]
                result = driver.execute_script("""
                    const tags = arguments[0];
                    const sel = document.querySelector('#tags');
                    if (!sel) return 'NO #tags';
                    if (window.jQuery && window.jQuery(sel).data('select2')) {
                        const $s = window.jQuery(sel);
                        for (const t of tags) {
                            if (![...sel.options].some(o => o.value === t)) {
                                $s.append(new Option(t, t, true, true));
                            }
                        }
                        $s.val(tags).trigger('change');
                        return 'select2: ' + $s.val().length + ' tags set';
                    }
                    for (const t of tags) {
                        sel.add(new Option(t, t, true, true));
                    }
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'native: ' + [...sel.selectedOptions].length + ' tags set';
                """, tag_list)
                print("[+] tags:", result)
            if args.unpublish:
                state = driver.execute_script("""
                    const cb = document.querySelector("input[name='is_public']");
                    if (!cb) return 'MISSING';
                    if (cb.checked) { cb.click(); }
                    return cb.checked ? 'STILL CHECKED' : 'unchecked';
                """)
                print("[+] is_public:", state)
                if state != "unchecked":
                    print("[FAIL] could not uncheck is_public")
                    return 1
            saved = driver.execute_script("""
                const b = [...document.querySelectorAll('button')]
                    .find(e => e.textContent.trim() === 'Save');
                if (b) { b.click(); return true; }
                return false;
            """)
            print("[+] save clicked:", saved)
            time.sleep(8)
            return 0 if saved else 1
        if args.row_html and row_link:
            html = driver.execute_script("""
                const el = arguments[0];
                const row = el.closest('tr, li, .row, [class*=beat], [class*=item]') || el.parentElement.parentElement;
                return row ? row.outerHTML.slice(0, 5000) : 'NO ROW';
            """, row_link)
            print("ROW HTML:\n", html)
            return 0
        if not url:
            print("[FAIL] H00DR1CH not found in beats list; first rows:")
            for link in driver.find_elements(By.CSS_SELECTOR, "h4 a[href*='/beats/']")[:10]:
                print("   ROW: %r %s" % (link.text, link.get_attribute("href")))
            return 1
        driver.get(url)
        time.sleep(15)
        # open the Files tab
        nav = driver.execute_script("""
            return [...document.querySelectorAll('a, button, li')]
                .filter(e => (e.textContent||'').trim().match(/^(Files|Beat Details|Pricing|Scheduled & Visibility|Co-producers & Songs)$/))
                .map(e => e.tagName + '.' + e.className + ' | ' + e.textContent.trim() + ' | href=' + (e.getAttribute('href')||''));
        """)
        print("NAV CANDIDATES:", *nav, sep="\n  ")
        clicked = driver.execute_script("""
            const els = [...document.querySelectorAll('a, button, li')]
                .filter(e => (e.textContent||'').trim() === 'Files');
            if (els.length) { const t = els[els.length-1]; t.click(); return t.tagName + '.' + t.className; }
            return null;
        """)
        print("[+] Files tab click:", clicked)
        time.sleep(5)
        html = driver.execute_script("""
            const btn = [...document.querySelectorAll('button, a')].find(e => e.textContent.trim() === 'MP3');
            const sec = btn ? btn.closest('div.tab-pane, section, form, div') : null;
            return sec ? sec.outerHTML.slice(0, 4000) : 'NOT FOUND';
        """)
        print("FILES SECTION HTML:\n", html)

        if args.replace:
            beat_path = Path(args.file).resolve()
            if not beat_path.exists():
                print("[FAIL] no such file:", beat_path)
                return 1
            target = None
            for fi in driver.find_elements(By.CSS_SELECTOR, "input[type='file']"):
                accept = (fi.get_attribute("accept") or "").lower()
                name = (fi.get_attribute("name") or "").lower()
                if "audio" in accept or "mp3" in accept or ("artwork" not in name and "image" not in accept):
                    target = fi
                    break
            if target is None:
                print("[FAIL] no audio file input on edit page")
                return 1
            driver.execute_script(
                "arguments[0].style.display='block';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].style.opacity='1';", target)
            time.sleep(0.3)
            target.send_keys(str(beat_path))
            print("[+] sent", beat_path)
            print("[~] waiting for Airbit to process replacement...")
            time.sleep(25)
            # save
            saved = False
            for sel in ("#beats-edit-form button[type='submit']",
                        "button[type='submit']"):
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    driver.execute_script("arguments[0].click();", els[0])
                    saved = True
                    print("[+] clicked save:", sel)
                    break
            if not saved:
                print("[FAIL] no save button found")
                return 1
            time.sleep(10)
            print("[DONE] final url:", driver.current_url)
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
