package com.family.englishdiary;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {
    private static final String START_URL = "https://192.168.5.4:8443/";
    private static final int REQUEST_AUDIO = 1002;
    private static final int REQUEST_GALLERY = 1003;
    private static final int REQUEST_CAMERA = 1004;
    private static final int REQUEST_CROP = 1005;

    private WebView webView;
    private ValueCallback<Uri[]> pendingFileCallback;
    private PermissionRequest pendingPermissionRequest;
    private Uri pendingCameraUri;
    private Uri pendingCropOutputUri;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        setContentView(
                webView,
                new ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT));

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(
                settings.getUserAgentString() + " FamilyDiaryShell/1.0");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(
                new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(
                            WebView view, WebResourceRequest request) {
                        Uri uri = request.getUrl();
                        if ("https".equals(uri.getScheme())
                                && "192.168.5.4".equals(uri.getHost())) {
                            return false;
                        }
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        } catch (Exception ignored) {
                            // Ignore links that no installed app can handle.
                        }
                        return true;
                    }

                    @Override
                    public void onReceivedSslError(
                            WebView view,
                            SslErrorHandler handler,
                            android.net.http.SslError error) {
                        handler.cancel();
                        Toast.makeText(
                                        MainActivity.this,
                                        "HTTPS 证书不受信任，请先在手机安装并信任证书。",
                                        Toast.LENGTH_LONG)
                                .show();
                    }
                });

        webView.setWebChromeClient(
                new WebChromeClient() {
                    @Override
                    public void onPermissionRequest(final PermissionRequest request) {
                        runOnUiThread(
                                () -> {
                                    List<String> audioResources = new ArrayList<>();
                                    for (String resource : request.getResources()) {
                                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE
                                                .equals(resource)) {
                                            audioResources.add(resource);
                                        }
                                    }
                                    if (audioResources.isEmpty()) {
                                        request.deny();
                                        return;
                                    }
                                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                                            == PackageManager.PERMISSION_GRANTED) {
                                        request.grant(
                                                audioResources.toArray(new String[0]));
                                    } else {
                                        if (pendingPermissionRequest != null) {
                                            pendingPermissionRequest.deny();
                                        }
                                        pendingPermissionRequest = request;
                                        requestPermissions(
                                                new String[] {
                                                    Manifest.permission.RECORD_AUDIO
                                                },
                                                REQUEST_AUDIO);
                                    }
                                });
                    }

                    @Override
                    public boolean onShowFileChooser(
                            WebView view,
                            ValueCallback<Uri[]> filePathCallback,
                            FileChooserParams fileChooserParams) {
                        if (pendingFileCallback != null) {
                            pendingFileCallback.onReceiveValue(null);
                        }
                        pendingFileCallback = filePathCallback;
                        showImageSourceDialog();
                        return true;
                    }
                });

        webView.loadUrl(START_URL);
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_AUDIO) {
            return;
        }
        PermissionRequest request = pendingPermissionRequest;
        pendingPermissionRequest = null;
        if (request == null) {
            return;
        }
        if (grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            List<String> audioResources = new ArrayList<>();
            for (String resource : request.getResources()) {
                if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                    audioResources.add(resource);
                }
            }
            request.grant(audioResources.toArray(new String[0]));
        } else {
            request.deny();
        }
    }

    private void showImageSourceDialog() {
        new AlertDialog.Builder(this)
                .setTitle("添加照片")
                .setItems(
                        new CharSequence[] {"拍照", "从相册选择"},
                        (dialog, which) -> {
                            if (which == 0) {
                                startCamera();
                            } else {
                                startGallery();
                            }
                        })
                .setNegativeButton("取消", (dialog, which) -> finishFile(null))
                .setOnCancelListener(dialog -> finishFile(null))
                .show();
    }

    private void startCamera() {
        File file =
                new File(
                        SharedFileProvider.directory(this),
                        "capture_" + System.currentTimeMillis() + ".jpg");
        pendingCameraUri = SharedFileProvider.uriFor(file);

        Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        intent.putExtra(MediaStore.EXTRA_OUTPUT, pendingCameraUri);
        intent.setClipData(ClipData.newRawUri("capture", pendingCameraUri));
        intent.addFlags(
                Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivityForResult(intent, REQUEST_CAMERA);
        } catch (Exception exception) {
            pendingCameraUri = null;
            Toast.makeText(this, "无法打开相机。", Toast.LENGTH_SHORT).show();
            finishFile(null);
        }
    }

    private void startGallery() {
        Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        try {
            startActivityForResult(Intent.createChooser(intent, "选择图片"), REQUEST_GALLERY);
        } catch (Exception exception) {
            Toast.makeText(this, "无法打开相册。", Toast.LENGTH_SHORT).show();
            finishFile(null);
        }
    }

    private void startCrop(Uri inputUri) {
        if (inputUri == null) {
            finishFile(null);
            return;
        }
        File output =
                new File(
                        SharedFileProvider.directory(this),
                        "crop_" + System.currentTimeMillis() + ".jpg");
        pendingCropOutputUri = SharedFileProvider.uriFor(output);

        Intent intent = new Intent(this, CropActivity.class);
        intent.putExtra(CropActivity.EXTRA_INPUT_URI, inputUri.toString());
        intent.putExtra(CropActivity.EXTRA_OUTPUT_URI, pendingCropOutputUri.toString());
        try {
            startActivityForResult(intent, REQUEST_CROP);
        } catch (Exception exception) {
            pendingCropOutputUri = null;
            Toast.makeText(this, "无法打开裁剪页面。", Toast.LENGTH_SHORT).show();
            finishFile(null);
        }
    }

    private void finishFile(Uri uri) {
        ValueCallback<Uri[]> callback = pendingFileCallback;
        pendingFileCallback = null;
        pendingCameraUri = null;
        pendingCropOutputUri = null;
        if (callback != null) {
            callback.onReceiveValue(uri == null ? null : new Uri[] {uri});
        }
    }

    private boolean cameraFileHasContent(Uri uri) {
        if (uri == null) {
            return false;
        }
        String name = uri.getLastPathSegment();
        if (name == null) {
            return false;
        }
        File file = new File(SharedFileProvider.directory(this), name);
        return file.isFile() && file.length() > 0;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);

        if (requestCode == REQUEST_CAMERA) {
            if (resultCode == RESULT_OK && cameraFileHasContent(pendingCameraUri)) {
                startCrop(pendingCameraUri);
            } else {
                Toast.makeText(this, "没有拍到照片。", Toast.LENGTH_SHORT).show();
                finishFile(null);
            }
            return;
        }

        if (requestCode == REQUEST_GALLERY) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                startCrop(data.getData());
            } else {
                finishFile(null);
            }
            return;
        }

        if (requestCode == REQUEST_CROP) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                finishFile(data.getData());
            } else {
                finishFile(null);
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
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
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.loadUrl("about:blank");
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
