/**
 * barcode_scanner.js
 * ─────────────────────────────────────────────────────────────
 * Drop this file in your static/js/ folder and add this line
 * just before </body> in sales/index.html:
 *
 *   <script src="{{ url_for('static', filename='js/barcode_scanner.js') }}"></script>
 *
 * Requirements from your existing sales page:
 *   - A global `cart` array of cart item objects
 *   - A global `renderCart()` function that redraws the cart UI
 *   - A global `showToast(message, type)` function for notifications
 * ─────────────────────────────────────────────────────────────
 */

(function () {
  "use strict";

  let buf   = "";
  let timer = null;

  /* ── Web Audio beep sounds (no audio files needed) ──────── */
  function beep(freq, dur, type = "sine", vol = 0.4) {
    try {
      const ctx  = new (window.AudioContext || window.webkitAudioContext)();
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type            = type;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(vol, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + dur);
    } catch (e) {
      /* AudioContext blocked before user gesture — silently ignore */
    }
  }

  /** Two rising tones — item added to cart */
  function soundSuccess() {
    beep(1046, 0.12);
    setTimeout(() => beep(1318, 0.15), 110);
  }

  /** Harsh buzz — error / out of stock / not found */
  function soundError() {
    beep(220, 0.35, "sawtooth", 0.5);
  }

  /** Single mid tone — item qty incremented (already in cart) */
  function soundDuplicate() {
    beep(880, 0.1);
  }

  /** Soft warning tone — stock limit reached */
  function soundWarning() {
    beep(520, 0.2, "triangle", 0.4);
  }

  /* ── Keyboard capture ───────────────────────────────────── */
  /*
   * USB / Bluetooth barcode scanners act as HID keyboard devices.
   * They send the full barcode string in < 50 ms then fire Enter.
   * Normal human typing is far slower (> 200 ms per character).
   * Strategy:
   *   - Accumulate characters into `buf` when typing is fast
   *   - Reset `buf` if gap between keystrokes exceeds 200 ms
   *   - On Enter, if buf length > 2 treat it as a scanned barcode
   *   - Ignore events when a real input/textarea/select is focused
   */
  document.addEventListener("keydown", function (e) {
    const tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === "Enter") {
      const code = buf.trim();
      buf = "";
      clearTimeout(timer);
      if (code.length > 2) {
        handleBarcode(code);
      }
    } else if (e.key.length === 1) {
      buf += e.key;
      clearTimeout(timer);
      /* reset buffer if scanner pauses more than 200 ms */
      timer = setTimeout(function () { buf = ""; }, 200);
    }
  });

  /* ── Barcode handler ─────────────────────────────────────── */
  async function handleBarcode(code) {
    try {
      const res  = await fetch("/sales/api/barcode/" + encodeURIComponent(code));
      const data = await res.json();

      if (!data.success) {
        soundError();
        showToast(data.message || "Product not found.", "danger");
        return;
      }

      const p        = data.product;
      const existing = cart.find(function (i) {
        return i.product_id === p.product_id;
      });

      if (existing) {
        /* product already in cart — try to increment qty */
        if (existing.qty < p.quantity) {
          existing.qty += 1;
          soundDuplicate();
          showToast(p.name + " qty → " + existing.qty, "info");
        } else {
          soundWarning();
          showToast("Max stock reached for " + p.name + " (" + p.quantity + " left)", "warning");
        }
      } else {
        /* new product — push to cart */
        cart.push({
          product_id:   p.product_id,
          product_name: p.name,
          category:     p.category  || "",
          unit_price:   p.unit_price,
          qty:          1,
          gst_pct:      p.gst_pct  || 0,
          disc_type:    "Flat",
          disc_val:     0,
        });
        soundSuccess();
        showToast("✔ " + p.name + " added to cart", "success");
      }

      /* re-render the cart table */
      if (typeof renderCart === "function") {
        renderCart();
      }

    } catch (err) {
      soundError();
      console.error("Barcode lookup error:", err);
      showToast("Barcode lookup failed. Check connection.", "danger");
    }
  }

  /* ── stock_conflict handler (call from your checkout response) ──
   *
   * In your existing checkout fetch() callback, add:
   *
   *   if (data.stock_conflict) {
   *     handleStockConflict(data.product_id, data.available, data.message);
   *   }
   *
   * ─────────────────────────────────────────────────────────── */
  window.handleStockConflict = function (productId, available, message) {
    soundError();
    showToast(message, "warning");

    /* update qty in cart so it does not exceed available stock */
    const item = cart.find(function (i) { return i.product_id === productId; });
    if (item) {
      item.qty = Math.min(item.qty, available);
    }
    if (typeof renderCart === "function") {
      renderCart();
    }
  };

  console.info("[BarcodeScanner] Loaded — listening for scanner input.");

})();