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
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
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
        val sharedUrl = extractSharedUrl(intent)
        setContent {
            StripWallTheme {
                StripWallScreen(initialUrl = sharedUrl)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Re-check for share-intent when activity already running
    }

    private fun extractSharedUrl(intent: Intent?): String? {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            return intent.getStringExtra(Intent.EXTRA_TEXT)
                ?.trim()
                ?.split(" ")
                ?.firstOrNull { it.startsWith("http") }
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
    var displayUrl by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var backendStatus by remember { mutableStateOf<BackendState>(BackendState.Unknown) }
    var canGoBack by remember { mutableStateOf(false) }
    var canGoForward by remember { mutableStateOf(false) }
    var cleanupMode by remember { mutableStateOf(false) }

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }
    val focusManager = LocalFocusManager.current

    // Check backend health on launch
    LaunchedEffect(Unit) {
        backendStatus = BackendState.Checking
        val ok = checkBackendHealth()
        backendStatus = if (ok) BackendState.Online else BackendState.Offline
    }

    // ── Navigate ────────────────────────────────────────────────────
    fun navigate(url: String) {
        val cleanUrl = url.trim().let {
            if (!it.startsWith("http")) "https://$it" else it
        }
        currentUrl = cleanUrl
        displayUrl = cleanUrl
        val proxyUrl = buildProxyUrl(cleanUrl)
        webView?.loadUrl(proxyUrl)
        focusManager.clearFocus()
    }

    // ── Toggle cleanup ──────────────────────────────────────────────
    fun toggleCleanup() {
        cleanupMode = !cleanupMode
        val js = if (cleanupMode) {
            // Find the clean button in the injected toolbar and click it
            """(function(){
                var btn = document.getElementById('sw-btn');
                if(btn) { btn.click(); return 'toggled'; }
                return 'no-toolbar';
            })();"""
        } else {
            // If we turned it off, also try clicking button to sync
            """(function(){
                var btn = document.getElementById('sw-btn');
                var isActive = btn && btn.classList.contains('sw-active');
                if(isActive) { btn.click(); return 'deactivated'; }
                return 'already-off';
            })();"""
        }
        webView?.evaluateJavascript(js, null)
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Text("StripWall", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                actions = {
                    BackendIndicator(backendStatus)
                }
            )
        },
        bottomBar = {
            if (currentUrl != null) {
                Surface(
                    color = MaterialTheme.colorScheme.surface,
                    tonalElevation = 4.dp,
                    shadowElevation = 8.dp,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 4.dp)
                            .navigationBarsPadding(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Back
                        IconButton(
                            onClick = { webView?.goBack(); updateNavState(webView, { canGoBack = it }, { canGoForward = it }) },
                            enabled = canGoBack,
                            modifier = Modifier.size(36.dp),
                        ) {
                            Icon(Icons.Default.ArrowBack, "Back", tint = if (canGoBack) Color(0xFFE8EAED) else Color(0xFF5F6368))
                        }
                        // Forward
                        IconButton(
                            onClick = { webView?.goForward(); updateNavState(webView, { canGoBack = it }, { canGoForward = it }) },
                            enabled = canGoForward,
                            modifier = Modifier.size(36.dp),
                        ) {
                            Icon(Icons.Default.ArrowForward, "Forward", tint = if (canGoForward) Color(0xFFE8EAED) else Color(0xFF5F6368))
                        }

                        // URL bar
                        OutlinedTextField(
                            value = displayUrl,
                            onValueChange = { displayUrl = it },
                            placeholder = { Text("URL...", fontSize = 12.sp, color = Color(0xFF5F6368)) },
                            modifier = Modifier
                                .weight(1f)
                                .height(40.dp),
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp),
                            textStyle = MaterialTheme.typography.bodySmall.copy(color = Color(0xFFE8EAED), fontSize = 12.sp),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = Color(0xFF8AB4F8),
                                unfocusedBorderColor = Color(0xFF3D3D3D),
                                cursorColor = Color(0xFF8AB4F8),
                                focusedContainerColor = Color(0xFF0D1117),
                                unfocusedContainerColor = Color(0xFF0D1117),
                            ),
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Uri,
                                imeAction = ImeAction.Go,
                            ),
                            keyboardActions = KeyboardActions(
                                onGo = {
                                    navigate(displayUrl)
                                }
                            ),
                        )

                        Spacer(Modifier.width(4.dp))

                        // Go button
                        FilledTonalButton(
                            onClick = { navigate(displayUrl) },
                            enabled = displayUrl.isNotBlank() && backendStatus != BackendState.Offline,
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                            modifier = Modifier.height(36.dp),
                            shape = RoundedCornerShape(10.dp),
                            colors = ButtonDefaults.filledTonalButtonColors(containerColor = Color(0xFF2D2D2D)),
                        ) {
                            Text("Ir", fontSize = 12.sp, color = Color(0xFFE8EAED))
                        }

                        Spacer(Modifier.width(4.dp))

                        // Clean toggle
                        FilledTonalButton(
                            onClick = { toggleCleanup() },
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                            modifier = Modifier.height(36.dp),
                            shape = RoundedCornerShape(10.dp),
                            colors = ButtonDefaults.filledTonalButtonColors(
                                containerColor = if (cleanupMode) Color(0xFFF28B82) else Color(0xFF2D2D2D)
                            ),
                        ) {
                            Text(
                                if (cleanupMode) "✔" else "✂",
                                fontSize = 14.sp,
                                color = if (cleanupMode) Color.White else Color(0xFFE8EAED),
                            )
                        }

                        Spacer(Modifier.width(4.dp))

                        // Home
                        IconButton(
                            onClick = {
                                currentUrl = null
                                displayUrl = ""
                                inputUrl = ""
                                cleanupMode = false
                            },
                            modifier = Modifier.size(36.dp),
                        ) {
                            Icon(Icons.Default.Home, "Home", tint = Color(0xFF9AA0A6))
                        }
                    }
                }
            }
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            if (currentUrl == null) {
                // ── Home screen ─────────────────────────────────────────
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background)
                        .padding(32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        "⚡ StripWall",
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFF8AB4F8),
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Navegá sin paywalls ni popups",
                        fontSize = 14.sp,
                        color = Color(0xFF9AA0A6),
                    )
                    Spacer(Modifier.height(24.dp))
                    OutlinedTextField(
                        value = inputUrl,
                        onValueChange = { inputUrl = it },
                        placeholder = {
                            Text(
                                "URL del artículo",
                                fontSize = 14.sp,
                                color = Color(0xFF5F6368),
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        textStyle = MaterialTheme.typography.bodyLarge.copy(color = Color(0xFFE8EAED)),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Color(0xFF8AB4F8),
                            unfocusedBorderColor = Color(0xFF3D3D3D),
                            cursorColor = Color(0xFF8AB4F8),
                            focusedContainerColor = Color(0xFF1E1E1E),
                            unfocusedContainerColor = Color(0xFF1E1E1E),
                        ),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Uri,
                            imeAction = ImeAction.Go,
                        ),
                        keyboardActions = KeyboardActions(
                            onGo = { navigate(inputUrl) }
                        ),
                        trailingIcon = {
                            if (inputUrl.isNotEmpty()) {
                                IconButton(onClick = { inputUrl = "" }) {
                                    Icon(Icons.Default.Clear, "Clear", tint = Color(0xFF5F6368))
                                }
                            }
                        },
                    )
                    Spacer(Modifier.height(12.dp))
                    Button(
                        onClick = { navigate(inputUrl) },
                        enabled = inputUrl.isNotBlank() && backendStatus != BackendState.Offline,
                        shape = RoundedCornerShape(12.dp),
                        contentPadding = PaddingValues(horizontal = 32.dp, vertical = 14.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF8AB4F8)),
                    ) {
                        if (backendStatus == BackendState.Checking) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                                color = Color(0xFF0D1117),
                            )
                        } else {
                            Text("Ir", fontWeight = FontWeight.Bold, color = Color(0xFF0D1117))
                        }
                    }

                    if (backendStatus == BackendState.Offline) {
                        Spacer(Modifier.height(12.dp))
                        Text(
                            "⚠ Servidor no disponible. Revisá tu conexión.",
                            fontSize = 12.sp,
                            color = Color(0xFFF28B82),
                        )
                    }

                    Spacer(Modifier.height(24.dp))
                    Text(
                        "Compartí un enlace desde cualquier app\npara abrirlo directamente en StripWall.",
                        fontSize = 12.sp,
                        color = Color(0xFF5F6368),
                        lineHeight = 18.sp,
                    )
                }
            } else {
                // ── WebView (full screen) ───────────────────────────
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
                                    userAgentString = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
                                }

                                webViewClient = object : WebViewClient() {
                                    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                        isLoading = true
                                    }

                                    override fun onPageFinished(view: WebView?, url: String?) {
                                        isLoading = false
                                        // Update navigation state
                                        view?.let { v ->
                                            canGoBack = v.canGoBack()
                                            canGoForward = v.canGoForward()
                                        }
                                        // Extract real URL from proxy URL
                                        val realUrl = extractRealUrl(url)
                                        if (realUrl != null) {
                                            displayUrl = realUrl
                                        } else if (url != null) {
                                            displayUrl = url
                                        }
                                        // Re-apply padding for bottom toolbar
                                        view?.evaluateJavascript(
                                            "document.body.style.paddingBottom = '52px';",
                                            null
                                        )
                                    }

                                    override fun shouldOverrideUrlLoading(
                                        view: WebView?,
                                        request: WebResourceRequest?
                                    ): Boolean {
                                        val url = request?.url?.toString() ?: return false
                                        val host = Uri.parse(url).host ?: return false

                                        // Always let our own domain load normally
                                        if (host.contains("stripwall.amago.fyi")) {
                                            return false
                                        }

                                        // Intercept external URLs and route through proxy
                                        val proxyUrl = buildProxyUrl(url)
                                        view?.loadUrl(proxyUrl)
                                        return true
                                    }

                                    override fun doUpdateVisitedHistory(view: WebView?, url: String?, isReload: Boolean) {
                                        view?.let { v ->
                                            canGoBack = v.canGoBack()
                                            canGoForward = v.canGoForward()
                                        }
                                        val realUrl = extractRealUrl(url)
                                        if (realUrl != null) {
                                            displayUrl = realUrl
                                        } else if (url != null) {
                                            displayUrl = url
                                        }
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

                                // Load initial URL if set
                                currentUrl?.let { url ->
                                    val proxyUrl = buildProxyUrl(url)
                                    loadUrl(proxyUrl)
                                }
                            }
                        },
                        modifier = Modifier.fillMaxSize(),
                    )

                    // Loading bar (top)
                    AnimatedVisibility(
                        visible = isLoading,
                        modifier = Modifier.align(Alignment.TopCenter),
                    ) {
                        LinearProgressIndicator(
                            modifier = Modifier.fillMaxWidth(),
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }

                    // Floating hint when cleanup mode is on
                    if (cleanupMode) {
                        Surface(
                            modifier = Modifier
                                .align(Alignment.TopCenter)
                                .padding(top = 8.dp),
                            shape = RoundedCornerShape(20.dp),
                            color = Color(0xFFF28B82).copy(alpha = 0.9f),
                            shadowElevation = 4.dp,
                        ) {
                            Text(
                                "Tocá elementos para eliminarlos · ← para salir",
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                                fontSize = 12.sp,
                                color = Color.White,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
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

private fun buildProxyUrl(targetUrl: String): String {
    val cleanTarget = targetUrl.trim().let {
        if (!it.startsWith("http")) "https://$it" else it
    }
    return "${getBackendHost()}/proxy?url=${Uri.encode(cleanTarget)}"
}

private fun extractRealUrl(proxyUrl: String?): String? {
    if (proxyUrl == null) return null
    val uri = Uri.parse(proxyUrl)
    // Extract the `url` query parameter
    val encodedUrl = uri.getQueryParameter("url") ?: return null
    return Uri.decode(encodedUrl)
}

private fun updateNavState(
    webView: WebView?,
    setBack: (Boolean) -> Unit,
    setForward: (Boolean) -> Unit,
) {
    webView?.let { v ->
        setBack(v.canGoBack())
        setForward(v.canGoForward())
    }
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
