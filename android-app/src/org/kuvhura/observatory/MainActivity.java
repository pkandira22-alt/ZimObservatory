package org.kuvhura.observatory;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Message;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.DownloadListener;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

public class MainActivity extends Activity {

    private static final String[] INTERNAL_HOSTS = new String[] {
        "zimobservatory-backend.onrender.com",
        "ais-pre-fsejzx3v5zvxhqpgripvn4-744529076327.europe-west2.run.app",
        "pkandira22-alt.github.io"
    };

    private WebView webView;
    private ProgressBar topProgressBar;
    private LinearLayout splashOverlay;
    private LinearLayout errorOverlay;
    private TextView errorDetailText;

    private String primaryUrl;
    private String fallbackUrl;
    private boolean triedFallback = false;
    private boolean hasLoadedPage = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        primaryUrl = getString(R.string.primary_url);
        fallbackUrl = getString(R.string.fallback_url);

        configureSystemBars();
        setContentView(buildRootView());
        configureWebView();

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            loadStartUrl();
        }
    }

    private void configureSystemBars() {
        if (Build.VERSION.SDK_INT >= 21) {
            Window window = getWindow();
            window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            window.setStatusBarColor(Color.parseColor("#072B13"));
            window.setNavigationBarColor(Color.parseColor("#070B14"));
        }
    }

    private View buildRootView() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#070B14"));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#070B14"));
        root.addView(webView, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        ));

        topProgressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        topProgressBar.setMax(100);
        topProgressBar.setProgress(0);
        topProgressBar.setVisibility(View.GONE);
        ColorDrawable track = new ColorDrawable(Color.parseColor("#0F172A"));
        ClipDrawable fill = new ClipDrawable(
            new ColorDrawable(Color.parseColor("#22C55E")),
            Gravity.LEFT,
            ClipDrawable.HORIZONTAL
        );
        LayerDrawable barDrawable = new LayerDrawable(new android.graphics.drawable.Drawable[] { track, fill });
        barDrawable.setId(0, android.R.id.background);
        barDrawable.setId(1, android.R.id.progress);
        topProgressBar.setProgressDrawable(barDrawable);
        root.addView(topProgressBar, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            dp(3),
            Gravity.TOP
        ));

        splashOverlay = buildSplashOverlay();
        root.addView(splashOverlay, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        ));

        errorOverlay = buildErrorOverlay();
        errorOverlay.setVisibility(View.GONE);
        root.addView(errorOverlay, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        ));

        return root;
    }

    private LinearLayout buildSplashOverlay() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setGravity(Gravity.CENTER);
        container.setBackgroundColor(Color.parseColor("#070B14"));
        container.setPadding(dp(28), dp(28), dp(28), dp(28));

        TextView badge = new TextView(this);
        badge.setText("KUVHURA");
        badge.setTextColor(Color.parseColor("#F5C71A"));
        badge.setTextSize(TypedValue.COMPLEX_UNIT_SP, 28);
        badge.setTypeface(Typeface.DEFAULT_BOLD);
        badge.setGravity(Gravity.CENTER);
        container.addView(badge);

        TextView subtitle = new TextView(this);
        subtitle.setText("Zimbabwe Political Economy & Civic Observatory");
        subtitle.setTextColor(Color.parseColor("#CBD5E1"));
        subtitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        subParams.topMargin = dp(8);
        subParams.bottomMargin = dp(22);
        container.addView(subtitle, subParams);

        ProgressBar spinner = new ProgressBar(this);
        container.addView(spinner);

        TextView status = new TextView(this);
        status.setText("Connecting to live telemetry...");
        status.setTextColor(Color.parseColor("#94A3B8"));
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams stParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        stParams.topMargin = dp(14);
        container.addView(status, stParams);

        return container;
    }

    private LinearLayout buildErrorOverlay() {
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setGravity(Gravity.CENTER);
        container.setBackgroundColor(Color.parseColor("#070B14"));
        container.setPadding(dp(28), dp(28), dp(28), dp(28));

        TextView title = new TextView(this);
        title.setText("Unable to Reach KUVHURA Live Feed");
        title.setTextColor(Color.parseColor("#F8FAFC"));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        container.addView(title);

        errorDetailText = new TextView(this);
        errorDetailText.setText("Please check your internet connection and try again.");
        errorDetailText.setTextColor(Color.parseColor("#94A3B8"));
        errorDetailText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        errorDetailText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams detailParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        );
        detailParams.topMargin = dp(10);
        detailParams.bottomMargin = dp(22);
        container.addView(errorDetailText, detailParams);

        Button retryBtn = new Button(this);
        retryBtn.setText("Retry Connection");
        retryBtn.setAllCaps(false);
        retryBtn.setTextColor(Color.WHITE);
        retryBtn.setTypeface(Typeface.DEFAULT_BOLD);
        retryBtn.setPadding(dp(24), dp(12), dp(24), dp(12));
        GradientDrawable btnBg = new GradientDrawable();
        btnBg.setColor(Color.parseColor("#16A34A"));
        btnBg.setCornerRadius(dp(8));
        retryBtn.setBackground(btnBg);
        retryBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                triedFallback = false;
                errorOverlay.setVisibility(View.GONE);
                splashOverlay.setVisibility(View.VISIBLE);
                loadStartUrl();
            }
        });
        container.addView(retryBtn);

        return container;
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setCacheMode(isNetworkAvailable()
            ? WebSettings.LOAD_DEFAULT
            : WebSettings.LOAD_CACHE_ELSE_NETWORK);

        String defaultUa = settings.getUserAgentString();
        if (defaultUa != null && !defaultUa.contains("KuvhuraAndroidApp")) {
            settings.setUserAgentString(defaultUa + " KuvhuraAndroidApp/1.0");
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                errorOverlay.setVisibility(View.GONE);
                topProgressBar.setVisibility(View.VISIBLE);
                topProgressBar.setProgress(12);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                hasLoadedPage = true;
                topProgressBar.setVisibility(View.GONE);
                splashOverlay.setVisibility(View.GONE);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigationUrl(url);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (Build.VERSION.SDK_INT < 23) {
                    handleMainFrameError(failingUrl, description);
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (Build.VERSION.SDK_INT >= 23 && request != null && request.isForMainFrame()) {
                    String failingUrl = request.getUrl() != null ? request.getUrl().toString() : "";
                    String desc = error != null && error.getDescription() != null
                        ? error.getDescription().toString()
                        : "Network error";
                    handleMainFrameError(failingUrl, desc);
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (newProgress >= 100) {
                    topProgressBar.setVisibility(View.GONE);
                    splashOverlay.setVisibility(View.GONE);
                } else {
                    topProgressBar.setVisibility(View.VISIBLE);
                    topProgressBar.setProgress(Math.max(10, newProgress));
                }
            }

            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                WebView.HitTestResult result = view.getHitTestResult();
                if (result != null && result.getExtra() != null) {
                    openExternalUrl(result.getExtra());
                }
                return false;
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {
                openExternalUrl(url);
            }
        });
    }

    private void loadStartUrl() {
        webView.getSettings().setCacheMode(isNetworkAvailable()
            ? WebSettings.LOAD_DEFAULT
            : WebSettings.LOAD_CACHE_ELSE_NETWORK);
        webView.loadUrl(primaryUrl);
    }

    private void handleMainFrameError(String failingUrl, String description) {
        if (!triedFallback && fallbackUrl != null && !fallbackUrl.isEmpty()
            && (failingUrl == null || failingUrl.startsWith(primaryUrl))) {
            triedFallback = true;
            webView.loadUrl(fallbackUrl);
            return;
        }
        if (!hasLoadedPage) {
            splashOverlay.setVisibility(View.GONE);
            topProgressBar.setVisibility(View.GONE);
            errorDetailText.setText(
                isNetworkAvailable()
                    ? "The observatory server is waking up or temporarily unreachable (" + description + "). Tap Retry to reconnect."
                    : "Your device appears to be offline. Reconnect to Wi-Fi or mobile data and tap Retry."
            );
            errorOverlay.setVisibility(View.VISIBLE);
        }
    }

    private boolean handleNavigationUrl(String url) {
        if (url == null || url.isEmpty()) {
            return false;
        }
        Uri uri = Uri.parse(url);
        String scheme = uri.getScheme() != null ? uri.getScheme().toLowerCase() : "";
        if (!"http".equals(scheme) && !"https".equals(scheme)) {
            openExternalUrl(url);
            return true;
        }
        String host = uri.getHost() != null ? uri.getHost().toLowerCase() : "";
        for (String internalHost : INTERNAL_HOSTS) {
            if (host.equals(internalHost)) {
                if (url.toLowerCase().endsWith(".apk") || url.toLowerCase().endsWith(".pdf")) {
                    openExternalUrl(url);
                    return true;
                }
                return false;
            }
        }
        openExternalUrl(url);
        return true;
    }

    private void openExternalUrl(String url) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            startActivity(intent);
        } catch (ActivityNotFoundException ignored) {
            // No handler available on device
        }
    }

    private boolean isNetworkAvailable() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) return true;
            NetworkInfo active = cm.getActiveNetworkInfo();
            return active != null && active.isConnected();
        } catch (Exception e) {
            return true;
        }
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            value,
            getResources().getDisplayMetrics()
        ));
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) {
            webView.saveState(outState);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
