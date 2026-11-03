# واجهة JavaScript يستدعيها WebView بالاسم — لا تُعاد تسميتها
-keepclassmembers class com.darbstu.app.WebBridge {
    @android.webkit.JavascriptInterface <methods>;
}
