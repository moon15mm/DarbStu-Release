package com.darbstu.app

import android.webkit.JavascriptInterface

/**
 * الجسر بين صفحات النظام والتطبيق، متاح في الصفحة باسم `DarbAndroid`.
 *
 * ‏WebView في أندرويد لا يطبع بـ window.print ولا يحفظ ملفات blob: التي
 * تنشئها لوحة الويب (تصدير نور، التقارير، النماذج)، فالسكربت المحقون
 * (انظر [MainActivity.SHIM_JS]) يحوّل هذه النداءات إلى هنا.
 */
class WebBridge(private val activity: MainActivity) {

    @JavascriptInterface
    fun print() {
        activity.runOnUiThread { activity.printTop() }
    }

    @JavascriptInterface
    fun saveBase64(base64: String, mime: String, fileName: String) {
        activity.runOnUiThread { activity.saveBase64(base64, mime, fileName) }
    }

    @JavascriptInterface
    fun fail(message: String) {
        activity.runOnUiThread { activity.downloadFailed(message) }
    }

    @JavascriptInterface
    fun isApp(): Boolean = true
}
