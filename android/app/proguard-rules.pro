# Add project specific ProGuard rules here.
-keep class com.stripwall.app.BuildConfig { *; }
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
