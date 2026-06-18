package com.stripwall.app

import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.webkit.WebViewAssetLoader
import com.stripwall.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Grab URL from share intent
        val sharedUrl = extractSharedUrl(intent)

        setContent {
            StripWallTheme {
                StripWallScreen(initialUrl = sharedUrl)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Handle share-intent while activity already running
    }

    private fun extractSharedUrl(intent: Intent?): String? {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            return intent.getStringExtra(Intent.EXTRA_TEXT)
                ?.trim()
                ?.split(" ")
                ?.firstOrNull { it.startsWith("http")
            }
        }
        return null
    }
}

// ── Theme ─────────────────────────────────────────────────────────────

@Composable
fun StripWallTheme(content: @Composable () -> Unit) {
    val colorScheme = darkColorScheme(
        primary = Color(0xFF8AB4F8),
        secondary = Color(0xFFE8EAED),
        surface = Color(0xFF1E1E1E),
        background = Color(0xFF121212),
        onPrimary = Color(0xFF0D1117),
        onSecondary = Color(0xFF1E1E1E),
        onSurface = Color(0xFFE8EAED),
        onBackground = Color(0xFFE8EAED),
        surfaceVariant = Color(0xFF2D2D2D),
        onSurfaceVariant = Color(0xFFB0B0B0),
    )
    MaterialTheme(colorScheme = colorScheme) {
        content()
    }
}

// ── Main Screen ───────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StripWallScreen(initialUrl: String?) {
    var inputUrl by remember { mutableStateOf(initialUrl ?: "") }
    var currentUrl by remember { mutableStateOf<String?>(null) }
    var isLoading by remember { mutableStateOf(false) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var backendStatus by remember { mutableStateOf<BackendState>(BackendState.Unknown) }

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    // Check backend health on launch
    LaunchedEffect(Unit) {
        backendStatus = BackendState.Checking
        val ok = checkBackendHealth()
        backendStatus = if (ok) BackendState.Online else BackendState.Offline
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("StripWall", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                actions = {
                    // Backend status indicator
                    BackendIndicator(backendStatus)
                    // Reload current page
                    IconButton(onClick = {
                        currentUrl?.let { url ->
                            loadInWebView(webView, url)
                        }
                    }) {
                        Icon(Icons.Default.Refresh, "Reload")
                    }
                    // Open original URL in browser
                    IconButton(onClick = {
                        val originalUrl = inputUrl.trim().let { url ->
                            if (!url.startsWith("http")) "https://$url" else url
                        }
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(originalUrl))
                        context.startActivity(intent)
                    }) {
                        Icon(Icons.Default.OpenInNew, "Open original")
                    }
                }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            // ── URL Input Bar ────────────────────────────────────────
            Surface(
                tonalElevation = 2.dp,
                color = MaterialTheme.colorScheme.surface,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = inputUrl,
                        onValueChange = { inputUrl = it },
                        placeholder = { Text("https://example.com/article", fontSize = 14.sp) },
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Uri,
                            imeAction = ImeAction.Go,
                        ),
                        keyboardActions = KeyboardActions(
                            onGo = {
                                val url = inputUrl.trim()
                                if (url.isNotEmpty()) {
                                    currentUrl = url
                                    loadInWebView(webView, url)
                                }
                            }
                        ),
                        trailingIcon = {
                            if (inputUrl.isNotEmpty()) {
                                IconButton(onClick = { inputUrl = "" }) {
                                    Icon(Icons.Default.Clear, "Clear")
                                }
                            }
                        }
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = {
                            val url = inputUrl.trim()
                            if (url.isNotEmpty()) {
                                currentUrl = url
                                loadInWebView(webView, url)
                            }
                        },
                        enabled = inputUrl.isNotBlank() && backendStatus != BackendState.Offline,
                        shape = RoundedCornerShape(12.dp),
                        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
                    ) {
                        if (backendStatus == BackendState.Checking) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary,
                            )
                        } else {
                            Text("Go")
                        }
                    }
                }
            }

            // ── Loading indicator ────────────────────────────────────
            AnimatedVisibility(visible = isLoading) {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            // ── WebView ──────────────────────────────────────────────
            Box(modifier = Modifier.fillMaxSize()) {
                AndroidView(
                    factory = { ctx ->
                        WebView(ctx).apply {
                            layoutParams = ViewGroup.LayoutParams(
                                ViewGroup.LayoutParams.MATCH_PARENT,
                                ViewGroup.LayoutParams.MATCH_PARENT,
                            )

                            settings.apply {
                                javaScriptEnabled = true
                                domStorageEnabled = true
                                loadWithOverviewMode = true
                                useWideViewPort = true
                                builtInZoomControls = true
                                displayZoomControls = false
                                setSupportZoom(true)
                                allowFileAccess = false
                                allowContentAccess = false
                                // Mimic a desktop user-agent for better rendering
                                userAgentString = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                            }

                            webViewClient = object : WebViewClient() {
                                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                    isLoading = true
                                }

                                override fun onPageFinished(view: WebView?, url: String?) {
                                    isLoading = false
                                }

                                override fun shouldOverrideUrlLoading(
                                    view: WebView?,
                                    request: WebResourceRequest?
                                ): Boolean {
                                    // Stay within the WebView
                                    return false
                                }

                                override fun onReceivedError(
                                    view: WebView?,
                                    errorCode: Int,
                                    description: String?,
                                    failingUrl: String?
                                ) {
                                    isLoading = false
                                    scope.launch {
                                        snackbarHostState.showSnackbar(
                                            "Error ($errorCode): ${description ?: "Unknown"}",
                                            duration = SnackbarDuration.Long,
                                        )
                                    }
                                }
                            }

                            webChromeClient = object : WebChromeClient() {
                                override fun onProgressChanged(view: WebView?, newProgress: Int) {
                                    if (newProgress < 100) isLoading = true
                                    else isLoading = false
                                }
                            }

                            webView = this

                            // If initialized with a URL, load it immediately
                            currentUrl?.let { url ->
                                loadStripWallUrl(this, url)
                            }
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }
    }
}

// ── Backend indicator chip ────────────────────────────────────────────

enum class BackendState { Unknown, Online, Offline, Checking }

@Composable
fun BackendIndicator(state: BackendState) {
    val (color, label) = when (state) {
        BackendState.Online -> Color(0xFF4CAF50) to "Online"
        BackendState.Offline -> Color(0xFFE53935) to "Offline"
        BackendState.Checking -> Color(0xFFFFA726) to "Checking"
        BackendState.Unknown -> Color(0xFF9E9E9E) to "?"
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(end = 4.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(color)
        )
        Spacer(Modifier.width(4.dp))
        Text(label, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}


// ── Backend communication ─────────────────────────────────────────────

private fun getBackendHost(): String {
    return BuildConfig.BACKEND_HOST
}

private fun buildStripWallUrl(targetUrl: String): String {
    val cleanTarget = targetUrl.trim().let { url ->
        if (!url.startsWith("http")) "https://$url" else url
    }
    return "${getBackendHost()}/fetch?url=${Uri.encode(cleanTarget)}"
}

private fun loadStripWallUrl(webView: WebView?, targetUrl: String) {
    val stripWallUrl = buildStripWallUrl(targetUrl)
    webView?.loadUrl(stripWallUrl)
}

private fun loadInWebView(webView: WebView?, targetUrl: String) {
    loadStripWallUrl(webView, targetUrl)
}

private suspend fun checkBackendHealth(): Boolean {
    return withContext(Dispatchers.IO) {
        try {
            val client = OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(5, TimeUnit.SECONDS)
                .build()
            val request = Request.Builder()
                .url("${getBackendHost()}/ping")
                .build()
            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (e: Exception) {
            false
        }
    }
}
