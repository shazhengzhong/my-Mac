package com.family.englishdiary;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;

/** Read/write cache files for the camera, cropper, and WebView file input. */
public class SharedFileProvider extends ContentProvider {
    public static final String AUTHORITY = "com.family.englishdiary.files";
    private static final String DIRECTORY = "shared";

    public static File directory(Context context) {
        File directory = new File(context.getCacheDir(), DIRECTORY);
        if (!directory.exists()) {
            directory.mkdirs();
        }
        return directory;
    }

    public static Uri uriFor(File file) {
        return new Uri.Builder()
                .scheme("content")
                .authority(AUTHORITY)
                .appendPath(file.getName())
                .build();
    }

    private File fileFor(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || name.isEmpty() || name.contains("..") || name.contains("/")) {
            throw new FileNotFoundException("Invalid shared file name");
        }
        File directory = directory(getContext());
        File file = new File(directory, name);
        try {
            if (!file.getCanonicalFile()
                    .getParentFile()
                    .equals(directory.getCanonicalFile())) {
                throw new FileNotFoundException("Invalid shared file path");
            }
        } catch (IOException exception) {
            throw new FileNotFoundException("Invalid shared file path");
        }
        return file;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return "image/jpeg";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode)
            throws FileNotFoundException {
        File file = fileFor(uri);
        boolean read = mode.contains("r");
        boolean write = mode.contains("w") || mode.contains("a");
        int flags;
        if (read && write) {
            flags = ParcelFileDescriptor.MODE_READ_WRITE;
        } else if (write) {
            flags = ParcelFileDescriptor.MODE_WRITE_ONLY;
        } else {
            flags = ParcelFileDescriptor.MODE_READ_ONLY;
        }
        if (write) {
            flags |= ParcelFileDescriptor.MODE_CREATE;
        }
        if (mode.contains("w") && !mode.contains("a")) {
            flags |= ParcelFileDescriptor.MODE_TRUNCATE;
        }
        if (mode.contains("a")) {
            flags |= ParcelFileDescriptor.MODE_APPEND;
        }
        return ParcelFileDescriptor.open(file, flags);
    }

    @Override
    public Cursor query(
            Uri uri,
            String[] projection,
            String selection,
            String[] selectionArgs,
            String sortOrder) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        try {
            return fileFor(uri).delete() ? 1 : 0;
        } catch (FileNotFoundException exception) {
            return 0;
        }
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
