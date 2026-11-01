package com.family.englishdiary;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.View;

/** Displays a photo and a movable/resizable crop box. */
public class CropView extends View {
    private static final int MODE_NONE = 0;
    private static final int MODE_MOVE = 1;
    private static final int MODE_LEFT = 2;
    private static final int MODE_TOP = 4;
    private static final int MODE_RIGHT = 8;
    private static final int MODE_BOTTOM = 16;

    private final Paint imagePaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Paint dimPaint = new Paint();
    private final Paint borderPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint handlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF imageRect = new RectF();
    private final RectF cropRect = new RectF();
    private Bitmap bitmap;
    private int activeMode = MODE_NONE;
    private float lastX;
    private float lastY;

    public CropView(Context context) {
        super(context);
        setBackgroundColor(Color.BLACK);
        dimPaint.setColor(0x99000000);
        borderPaint.setColor(Color.WHITE);
        borderPaint.setStyle(Paint.Style.STROKE);
        borderPaint.setStrokeWidth(dp(2));
        gridPaint.setColor(0x55FFFFFF);
        gridPaint.setStyle(Paint.Style.STROKE);
        gridPaint.setStrokeWidth(dp(1));
        handlePaint.setColor(0xFF126B62);
        handlePaint.setStyle(Paint.Style.FILL);
    }

    public void setBitmap(Bitmap bitmap) {
        this.bitmap = bitmap;
        requestLayout();
        invalidate();
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        layoutImage();
    }

    private void layoutImage() {
        if (bitmap == null || getWidth() <= 0 || getHeight() <= 0) {
            return;
        }
        float padding = dp(14);
        float availableWidth = Math.max(1, getWidth() - padding * 2);
        float availableHeight = Math.max(1, getHeight() - padding * 2);
        float scale =
                Math.min(
                        availableWidth / bitmap.getWidth(),
                        availableHeight / bitmap.getHeight());
        float width = bitmap.getWidth() * scale;
        float height = bitmap.getHeight() * scale;
        float left = (getWidth() - width) / 2f;
        float top = (getHeight() - height) / 2f;
        imageRect.set(left, top, left + width, top + height);

        float insetX = width * 0.08f;
        float insetY = height * 0.08f;
        cropRect.set(
                imageRect.left + insetX,
                imageRect.top + insetY,
                imageRect.right - insetX,
                imageRect.bottom - insetY);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (bitmap == null || imageRect.isEmpty()) {
            return;
        }
        canvas.drawBitmap(bitmap, null, imageRect, imagePaint);

        canvas.drawRect(0, 0, getWidth(), cropRect.top, dimPaint);
        canvas.drawRect(0, cropRect.bottom, getWidth(), getHeight(), dimPaint);
        canvas.drawRect(0, cropRect.top, cropRect.left, cropRect.bottom, dimPaint);
        canvas.drawRect(cropRect.right, cropRect.top, getWidth(), cropRect.bottom, dimPaint);

        canvas.drawRect(cropRect, borderPaint);
        float thirdWidth = cropRect.width() / 3f;
        float thirdHeight = cropRect.height() / 3f;
        for (int index = 1; index <= 2; index++) {
            float x = cropRect.left + thirdWidth * index;
            float y = cropRect.top + thirdHeight * index;
            canvas.drawLine(x, cropRect.top, x, cropRect.bottom, gridPaint);
            canvas.drawLine(cropRect.left, y, cropRect.right, y, gridPaint);
        }

        float radius = dp(7);
        for (float[] corner :
                new float[][] {
                    {cropRect.left, cropRect.top},
                    {cropRect.right, cropRect.top},
                    {cropRect.left, cropRect.bottom},
                    {cropRect.right, cropRect.bottom}
                }) {
            canvas.drawCircle(corner[0], corner[1], radius, handlePaint);
        }
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX();
        float y = event.getY();
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                activeMode = modeAt(x, y);
                lastX = x;
                lastY = y;
                return activeMode != MODE_NONE;
            case MotionEvent.ACTION_MOVE:
                if (activeMode == MODE_NONE) {
                    return false;
                }
                moveCrop(x - lastX, y - lastY);
                lastX = x;
                lastY = y;
                return true;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                activeMode = MODE_NONE;
                return true;
            default:
                return super.onTouchEvent(event);
        }
    }

    private int modeAt(float x, float y) {
        float slop = dp(28);
        boolean left = Math.abs(x - cropRect.left) <= slop;
        boolean right = Math.abs(x - cropRect.right) <= slop;
        boolean top = Math.abs(y - cropRect.top) <= slop;
        boolean bottom = Math.abs(y - cropRect.bottom) <= slop;

        if (left && top) {
            return MODE_LEFT | MODE_TOP;
        }
        if (right && top) {
            return MODE_RIGHT | MODE_TOP;
        }
        if (left && bottom) {
            return MODE_LEFT | MODE_BOTTOM;
        }
        if (right && bottom) {
            return MODE_RIGHT | MODE_BOTTOM;
        }
        if (left) {
            return MODE_LEFT;
        }
        if (right) {
            return MODE_RIGHT;
        }
        if (top) {
            return MODE_TOP;
        }
        if (bottom) {
            return MODE_BOTTOM;
        }
        if (cropRect.contains(x, y)) {
            return MODE_MOVE;
        }
        return MODE_NONE;
    }

    private void moveCrop(float dx, float dy) {
        if (activeMode == MODE_MOVE) {
            cropRect.offset(dx, dy);
            if (cropRect.left < imageRect.left) {
                cropRect.offset(imageRect.left - cropRect.left, 0);
            }
            if (cropRect.right > imageRect.right) {
                cropRect.offset(imageRect.right - cropRect.right, 0);
            }
            if (cropRect.top < imageRect.top) {
                cropRect.offset(0, imageRect.top - cropRect.top);
            }
            if (cropRect.bottom > imageRect.bottom) {
                cropRect.offset(0, imageRect.bottom - cropRect.bottom);
            }
        } else {
            float minSize = dp(56);
            if ((activeMode & MODE_LEFT) != 0) {
                cropRect.left =
                        Math.max(
                                imageRect.left,
                                Math.min(cropRect.left + dx, cropRect.right - minSize));
            }
            if ((activeMode & MODE_RIGHT) != 0) {
                cropRect.right =
                        Math.min(
                                imageRect.right,
                                Math.max(cropRect.right + dx, cropRect.left + minSize));
            }
            if ((activeMode & MODE_TOP) != 0) {
                cropRect.top =
                        Math.max(
                                imageRect.top,
                                Math.min(cropRect.top + dy, cropRect.bottom - minSize));
            }
            if ((activeMode & MODE_BOTTOM) != 0) {
                cropRect.bottom =
                        Math.min(
                                imageRect.bottom,
                                Math.max(cropRect.bottom + dy, cropRect.top + minSize));
            }
        }
        invalidate();
    }

    public Rect getCropRectInBitmap() {
        if (bitmap == null || imageRect.isEmpty()) {
            return new Rect(0, 0, 1, 1);
        }
        float scale = imageRect.width() / bitmap.getWidth();
        int left = Math.round((cropRect.left - imageRect.left) / scale);
        int top = Math.round((cropRect.top - imageRect.top) / scale);
        int right = Math.round((cropRect.right - imageRect.left) / scale);
        int bottom = Math.round((cropRect.bottom - imageRect.top) / scale);
        left = Math.max(0, Math.min(left, bitmap.getWidth() - 1));
        top = Math.max(0, Math.min(top, bitmap.getHeight() - 1));
        right = Math.max(left + 1, Math.min(right, bitmap.getWidth()));
        bottom = Math.max(top + 1, Math.min(bottom, bitmap.getHeight()));
        return new Rect(left, top, right, bottom);
    }
}
