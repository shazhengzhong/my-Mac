package com.family.englishdiary;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Rect;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Lets the user crop a camera/gallery image before handing it to the WebView. */
public class CropActivity extends Activity {
    public static final String EXTRA_INPUT_URI = "input_uri";
    public static final String EXTRA_OUTPUT_URI = "output_uri";

    private static final int MAX_BITMAP_DIMENSION = 2560;
    private static final int MAX_OUTPUT_BYTES = 5 * 1024 * 1024;

    private CropView cropView;
    private Uri inputUri;
    private Uri outputUri;
    private Bitmap sourceBitmap;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);

        String input = getIntent().getStringExtra(EXTRA_INPUT_URI);
        String output = getIntent().getStringExtra(EXTRA_OUTPUT_URI);
        if (input == null || output == null) {
            finishCanceled();
            return;
        }
        inputUri = Uri.parse(input);
        outputUri = Uri.parse(output);

        try {
            sourceBitmap = loadBitmap(inputUri);
        } catch (Exception exception) {
            sourceBitmap = null;
        }
        if (sourceBitmap == null) {
            Toast.makeText(this, "无法读取这张照片，请换一张 JPG/PNG 图片。", Toast.LENGTH_LONG)
                    .show();
            finishCanceled();
            return;
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);

        TextView hint = new TextView(this);
        hint.setText("拖动方框，选择要识别的区域");
        hint.setTextColor(Color.WHITE);
        hint.setTextSize(16);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(0, (int) dp(14), 0, (int) dp(10));
        root.addView(
                hint,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        cropView = new CropView(this);
        cropView.setBitmap(sourceBitmap);
        root.addView(
                cropView,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        actions.setPadding((int) dp(14), (int) dp(8), (int) dp(14), (int) dp(14));

        Button cancel = new Button(this);
        cancel.setText("取消");
        cancel.setAllCaps(false);
        cancel.setOnClickListener(view -> finishCanceled());
        actions.addView(
                cancel,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        Button done = new Button(this);
        done.setText("完成");
        done.setAllCaps(false);
        done.setOnClickListener(view -> cropAndSave());
        actions.addView(
                done,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(
                actions,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(root);
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    private Bitmap loadBitmap(Uri uri) throws IOException {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        try (InputStream stream = getContentResolver().openInputStream(uri)) {
            if (stream == null) {
                return null;
            }
            BitmapFactory.decodeStream(stream, null, bounds);
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            return null;
        }

        int sampleSize = 1;
        while (Math.max(bounds.outWidth / sampleSize, bounds.outHeight / sampleSize)
                > MAX_BITMAP_DIMENSION) {
            sampleSize *= 2;
        }

        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sampleSize;
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;

        Bitmap bitmap;
        try (InputStream stream = getContentResolver().openInputStream(uri)) {
            if (stream == null) {
                return null;
            }
            bitmap = BitmapFactory.decodeStream(stream, null, options);
        }
        if (bitmap == null) {
            return null;
        }

        int orientation = ExifInterface.ORIENTATION_NORMAL;
        try (InputStream stream = getContentResolver().openInputStream(uri)) {
            if (stream != null) {
                ExifInterface exif = new ExifInterface(stream);
                orientation =
                        exif.getAttributeInt(
                                ExifInterface.TAG_ORIENTATION,
                                ExifInterface.ORIENTATION_NORMAL);
            }
        } catch (Exception ignored) {
            // EXIF is optional; use the decoded bitmap as-is.
        }
        return applyExifOrientation(bitmap, orientation);
    }

    private Bitmap applyExifOrientation(Bitmap bitmap, int orientation) {
        Matrix matrix = new Matrix();
        switch (orientation) {
            case ExifInterface.ORIENTATION_FLIP_HORIZONTAL:
                matrix.setScale(-1, 1);
                break;
            case ExifInterface.ORIENTATION_ROTATE_180:
                matrix.setRotate(180);
                break;
            case ExifInterface.ORIENTATION_FLIP_VERTICAL:
                matrix.setScale(1, -1);
                break;
            case ExifInterface.ORIENTATION_TRANSPOSE:
                matrix.setRotate(90);
                matrix.postScale(-1, 1);
                break;
            case ExifInterface.ORIENTATION_ROTATE_90:
                matrix.setRotate(90);
                break;
            case ExifInterface.ORIENTATION_TRANSVERSE:
                matrix.setRotate(-90);
                matrix.postScale(-1, 1);
                break;
            case ExifInterface.ORIENTATION_ROTATE_270:
                matrix.setRotate(-90);
                break;
            default:
                return bitmap;
        }
        try {
            Bitmap transformed =
                    Bitmap.createBitmap(
                            bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true);
            if (transformed != bitmap) {
                bitmap.recycle();
            }
            return transformed;
        } catch (Exception exception) {
            return bitmap;
        }
    }

    private void cropAndSave() {
        if (sourceBitmap == null || cropView == null) {
            finishCanceled();
            return;
        }
        Rect rect = cropView.getCropRectInBitmap();
        Bitmap cropped = null;
        try {
            cropped =
                    Bitmap.createBitmap(
                            sourceBitmap, rect.left, rect.top, rect.width(), rect.height());
            byte[] jpeg = compressToJpeg(cropped);
            if (jpeg == null) {
                throw new IOException("JPEG compression failed");
            }
            try (OutputStream stream = getContentResolver().openOutputStream(outputUri)) {
                if (stream == null) {
                    throw new IOException("Output stream unavailable");
                }
                stream.write(jpeg);
                stream.flush();
            }
            setResult(RESULT_OK, new Intent().setData(outputUri));
            finish();
        } catch (Exception exception) {
            Toast.makeText(this, "保存裁剪后的照片失败，请重试。", Toast.LENGTH_LONG).show();
            finishCanceled();
        } finally {
            if (cropped != null && cropped != sourceBitmap) {
                cropped.recycle();
            }
        }
    }

    private byte[] compressToJpeg(Bitmap bitmap) {
        Bitmap current = bitmap;
        boolean owned = false;
        try {
            for (int attempt = 0; attempt < 5; attempt++) {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                int quality = Math.max(55, 90 - attempt * 10);
                if (!current.compress(Bitmap.CompressFormat.JPEG, quality, output)) {
                    return null;
                }
                byte[] data = output.toByteArray();
                if (data.length <= MAX_OUTPUT_BYTES) {
                    return data;
                }
                int width = Math.max(1, Math.round(current.getWidth() * 0.8f));
                int height = Math.max(1, Math.round(current.getHeight() * 0.8f));
                Bitmap smaller = Bitmap.createScaledBitmap(current, width, height, true);
                if (owned) {
                    current.recycle();
                }
                current = smaller;
                owned = true;
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            if (current.compress(Bitmap.CompressFormat.JPEG, 55, output)) {
                return output.toByteArray();
            }
            return null;
        } finally {
            if (owned) {
                current.recycle();
            }
        }
    }

    private void finishCanceled() {
        setResult(RESULT_CANCELED);
        finish();
    }

    @Override
    public void onBackPressed() {
        finishCanceled();
    }

    @Override
    protected void onDestroy() {
        if (sourceBitmap != null) {
            sourceBitmap.recycle();
            sourceBitmap = null;
        }
        super.onDestroy();
    }
}
