package com.darbstu.app

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Message
import android.print.PrintAttributes
import android.print.PrintManager
import android.util.Base64
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.darbstu.app.databinding.ActivityMainBinding
import com.google.android.material.snackbar.Snackbar

/**
 * نظام المدرسة كاملاً داخل WebView: نفس لوحة الويب (/web/dashboard) التي
 * يستعملها المدير والوكيل والمعلم، بنفس الحسابات والصلاحيات — فكل ما
 * يضيفه النظام يظهر في التطبيق تلقائياً دون تحديثه.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private lateinit var host: String
    private var popup: WebView? = null
    private var popupFrame: View? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var lastBack = 0L

    private val pickFile = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val uris = WebChromeClient.FileChooserParams.parseResult(res.resultCode, res.data)
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)

        host = intent.getStringExtra(EXTRA_HOST) ?: run { finish(); return }
        title = intent.getStringExtra(EXTRA_NAME) ?: host

        CookieManager.getInstance().setAcceptCookie(true)
        setupWebView(b.web, isPopup = false)

        b.swipe.setColorSchemeColors(ContextCompat.getColor(this, R.color.blue))
        b.swipe.setOnChildScrollUpCallback { _, _ -> b.web.scrollY > 0 }
        b.swipe.setOnRefreshListener { b.web.reload() }
        b.retry.setOnClickListener {
            b.offline.visibility = View.GONE
            if (b.web.url.isNullOrEmpty() || b.web.url == "about:blank") b.web.loadUrl(startUrl())
            else b.web.reload()
        }
        b.switchSchool.setOnClickListener { finish() }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = onBack()
        })

        if (savedInstanceState != null) b.web.restoreState(savedInstanceState)
        else b.web.loadUrl(startUrl())
    }

    private fun startUrl() = "https://$host/web/dashboard"

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        b.web.saveState(outState)
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()   // يبقى المستخدم مسجّلاً بعد إغلاق التطبيق
    }

    // ═══════════════════════════════════════════════════════════════
    //  إعداد WebView
    // ═══════════════════════════════════════════════════════════════
    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView(web: WebView, isPopup: Boolean) {
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            javaScriptCanOpenWindowsAutomatically = true
            setSupportMultipleWindows(true)
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            mediaPlaybackRequiresUserGesture = true
            userAgentString = "$userAgentString DarbStuApp/${BuildConfig.VERSION_NAME}"
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.addJavascriptInterface(WebBridge(this), "DarbAndroid")

        // السكربت يُحقن قبل أي سكربت للصفحة، وفقط في نطاق المدرسة
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(web, SHIM_JS, setOf("https://$host"))
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                handleExternal(request.url)

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                if (!isPopup) b.offline.visibility = View.GONE
                if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT) && isSchoolUrl(url)) {
                    view.evaluateJavascript(SHIM_JS, null)
                }
            }

            override fun onPageFinished(view: WebView, url: String?) {
                if (!isPopup) b.swipe.isRefreshing = false
                // صفحات about:blank التي تكتبها اللوحة بـ document.write لا
                // يصلها السكربت المبكر، فنحقنه هنا أيضاً (محمي من التكرار).
                if (isSchoolUrl(url) || url == "about:blank") view.evaluateJavascript(SHIM_JS, null)
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame && !isPopup)
                    showOffline(getString(R.string.offline_body) + "\n\n" + host + "\n" + error.description)
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
                // 502/530 من Cloudflare = النفق يعمل لكن جهاز المدرسة مطفأ أو بلا إنترنت
                if (request.isForMainFrame && !isPopup && response.statusCode in setOf(502, 503, 504, 521, 522, 523, 530)) {
                    showOffline(getString(R.string.err_unreachable) + "\n\n" + host + " — HTTP " + response.statusCode)
                }
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                if (isPopup) return
                b.progress.progress = newProgress
                b.progress.visibility = if (newProgress < 100) View.VISIBLE else View.GONE
            }

            override fun onCreateWindow(view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message): Boolean {
                val child = openPopup()
                (resultMsg.obj as WebView.WebViewTransport).webView = child
                resultMsg.sendToTarget()
                return true
            }

            override fun onCloseWindow(window: WebView) {
                if (window == popup) closePopup()
            }

            override fun onShowFileChooser(
                webView: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                return try {
                    val intent = params.createIntent().apply {
                        if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) {
                            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                        }
                    }
                    pickFile.launch(Intent.createChooser(intent, getString(R.string.choose_file)))
                    true
                } catch (_: ActivityNotFoundException) {
                    fileCallback = null
                    false
                }
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            when {
                // ‏blob: ينتمي لسياق الصفحة التي أنشأته — نجلبه من النافذة الرئيسية
                url.startsWith("blob:") -> {
                    val name = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType)
                        .takeUnless { it.startsWith("downloadfile") }.orEmpty()
                    b.web.evaluateJavascript(
                        "window.darbSaveBlob && darbSaveBlob(${jsString(url)}, ${jsString(name)});", null)
                    if (isPopup) closePopup()
                }
                url.startsWith("data:") -> {
                    saveDataUrl(url)
                    if (isPopup) closePopup()
                }
                else -> {
                    try {
                        Downloads.enqueue(this, url, userAgent, contentDisposition, mimeType)
                        Toast.makeText(this, R.string.downloading, Toast.LENGTH_SHORT).show()
                    } catch (_: Exception) {
                        downloadFailed("")
                    }
                    if (isPopup) closePopup()
                }
            }
        }
    }

    private fun isSchoolUrl(url: String?): Boolean =
        url != null && Uri.parse(url).let { it.scheme == "https" && it.host == host }

    /** روابط خارج نطاق المدرسة (واتساب، هاتف، مواقع أخرى) تُفتح خارج التطبيق. */
    private fun handleExternal(uri: Uri): Boolean {
        val scheme = uri.scheme ?: return true
        if (scheme == "https" && uri.host == host) return false
        if (scheme == "about" || scheme == "blob" || scheme == "data") return false
        try {
            val intent = if (scheme == "intent") Intent.parseUri(uri.toString(), Intent.URI_INTENT_SCHEME)
            else Intent(Intent.ACTION_VIEW, uri)
            intent.addCategory(Intent.CATEGORY_BROWSABLE)
            intent.component = null
            intent.selector = null
            startActivity(intent)
        } catch (_: Exception) {
        }
        return true
    }

    private fun showOffline(msg: String) {
        b.swipe.isRefreshing = false
        b.offlineBody.text = msg
        b.offline.visibility = View.VISIBLE
    }

    // ═══════════════════════════════════════════════════════════════
    //  النوافذ المنبثقة (window.open) — الطباعة ومعاينة التقارير
    // ═══════════════════════════════════════════════════════════════
    private fun openPopup(): WebView {
        closePopup()
        val density = resources.displayMetrics.density
        val frame = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            isClickable = true
            elevation = 12 * density
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(ContextCompat.getColor(context, R.color.navy))
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        val close = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
            setBackgroundColor(Color.TRANSPARENT)
            setColorFilter(Color.WHITE)
            setOnClickListener { closePopup() }
        }
        val print = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_menu_upload)
            rotation = 180f
            setBackgroundColor(Color.TRANSPARENT)
            setColorFilter(Color.WHITE)
            contentDescription = "طباعة"
            setOnClickListener { printTop() }
        }
        val label = TextView(this).apply {
            text = title
            setTextColor(Color.WHITE)
            textSize = 16f
        }
        val size = (48 * density).toInt()
        bar.addView(close, LinearLayout.LayoutParams(size, size))
        bar.addView(label, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        bar.addView(print, LinearLayout.LayoutParams(size, size))

        val child = WebView(this)
        setupWebView(child, isPopup = true)
        frame.addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, size))
        frame.addView(child, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        (b.root as FrameLayout).addView(frame, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        popup = child
        popupFrame = frame
        return child
    }

    private fun closePopup() {
        val p = popup ?: return
        popup = null
        (b.root as FrameLayout).removeView(popupFrame)
        popupFrame = null
        p.stopLoading()
        p.destroy()
    }

    // ═══════════════════════════════════════════════════════════════
    //  الطباعة والحفظ (يستدعيها WebBridge)
    // ═══════════════════════════════════════════════════════════════
    fun printTop() {
        val target = popup ?: b.web
        // مهلة قصيرة: اللوحة تستدعي w.print() فور document.write قبل أن تُرسم الصفحة
        Handler(Looper.getMainLooper()).postDelayed({
            if (isFinishing) return@postDelayed
            val pm = getSystemService(PRINT_SERVICE) as PrintManager
            val job = "Darb - ${title ?: host}"
            pm.print(job, target.createPrintDocumentAdapter(job),
                PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build())
        }, 700)
    }

    fun saveBase64(base64: String, mime: String, fileName: String) {
        val bytes = try { Base64.decode(base64, Base64.DEFAULT) } catch (_: Exception) { null }
        if (bytes == null) { downloadFailed(""); return }
        val uri = Downloads.saveBytes(this, bytes, mime, fileName)
        if (uri == null) { downloadFailed(""); return }
        Snackbar.make(b.root, R.string.downloaded, Snackbar.LENGTH_LONG)
            .setAction(R.string.open) { Downloads.open(this, uri, mime) }
            .show()
        // ملفات PDF تُفتح مباشرة — منها يطبع المستخدم أو يشارك
        if (mime.startsWith("application/pdf")) Downloads.open(this, uri, mime)
    }

    private fun saveDataUrl(url: String) {
        val comma = url.indexOf(',')
        if (comma < 0) { downloadFailed(""); return }
        val meta = url.substring(5, comma)
        val mime = meta.substringBefore(';').ifBlank { "application/octet-stream" }
        val payload = url.substring(comma + 1)
        if (meta.endsWith(";base64")) saveBase64(payload, mime, "")
        else saveBase64(Base64.encodeToString(Uri.decode(payload).toByteArray(), Base64.NO_WRAP), mime, "")
    }

    fun downloadFailed(@Suppress("UNUSED_PARAMETER") message: String) {
        Toast.makeText(this, R.string.download_failed, Toast.LENGTH_SHORT).show()
    }

    // ═══════════════════════════════════════════════════════════════
    private fun onBack() {
        when {
            popup != null -> closePopup()
            b.web.canGoBack() -> b.web.goBack()
            System.currentTimeMillis() - lastBack < 2000 -> finish()
            else -> {
                lastBack = System.currentTimeMillis()
                Toast.makeText(this, R.string.press_back_again, Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroy() {
        closePopup()
        if (::b.isInitialized) b.web.destroy()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_HOST = "host"
        const val EXTRA_NAME = "name"

        private fun jsString(s: String): String =
            "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"

        /**
         * يُحقن في كل صفحة من صفحات المدرسة:
         *  • window.print ← طباعة أندرويد (ومثلها print النوافذ التي يفتحها window.open)
         *  • روابط blob: ذات download ← حفظ في «التنزيلات» (تصدير نور، النماذج، الجداول)
         */
        val SHIM_JS = """
            (function(){
              if (window.__darbShim || !window.DarbAndroid) return;
              window.__darbShim = true;
              document.documentElement && document.documentElement.classList.add('darb-app');
              window.print = function(){ DarbAndroid.print(); };
              window.darbSaveBlob = function(url, name){
                fetch(url).then(function(r){ return r.blob(); }).then(function(b){
                  var fr = new FileReader();
                  fr.onloadend = function(){
                    var s = String(fr.result || ''); var i = s.indexOf(',');
                    DarbAndroid.saveBase64(s.substring(i + 1), b.type || 'application/octet-stream', name || '');
                  };
                  fr.readAsDataURL(b);
                }).catch(function(e){ DarbAndroid.fail(String(e)); });
              };
              var _open = window.open;
              window.open = function(u, n, f){
                var w = _open.apply(window, arguments);
                try { if (w) w.print = function(){ DarbAndroid.print(); }; } catch(e) {}
                return w;
              };
              var _click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function(){
                if (this.href && this.href.indexOf('blob:') === 0) {
                  window.darbSaveBlob(this.href, this.getAttribute('download') || ''); return;
                }
                return _click.apply(this, arguments);
              };
              document.addEventListener('click', function(e){
                var a = e.target && e.target.closest && e.target.closest('a[href^="blob:"]');
                if (a) { e.preventDefault(); window.darbSaveBlob(a.href, a.getAttribute('download') || ''); }
              }, true);
            })();
        """.trimIndent()
    }
}
