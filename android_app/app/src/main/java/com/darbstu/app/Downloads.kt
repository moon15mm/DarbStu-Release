package com.darbstu.app

import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.CookieManager
import android.webkit.MimeTypeMap
import android.webkit.URLUtil
import androidx.core.content.FileProvider
import java.io.File

/** حفظ الملفات التي تنزّلها صفحات النظام في مجلد «التنزيلات» وفتحها. */
object Downloads {

    fun safeName(name: String, mime: String): String {
        var n = name.trim().replace(Regex("[\\\\/:*?\"<>|\\n\\r]"), "_")
        if (n.isEmpty()) n = "darb_" + System.currentTimeMillis()
        if (!n.contains('.')) {
            val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(mime.substringBefore(';'))
            if (ext != null) n += ".$ext"
        }
        return n
    }

    /** يكتب البايتات في التنزيلات ويُرجع رابطاً يمكن فتحه، أو null عند الفشل. */
    fun saveBytes(ctx: Context, bytes: ByteArray, mime: String, name: String): Uri? {
        val cleanMime = mime.substringBefore(';').ifBlank { "application/octet-stream" }
        val fileName = safeName(name, cleanMime)
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                    put(MediaStore.Downloads.MIME_TYPE, cleanMime)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Darb")
                }
                val uri = ctx.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: return null
                ctx.contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                uri
            } else {
                val dir = File(ctx.getExternalFilesDir(null), "Download").apply { mkdirs() }
                val file = File(dir, fileName)
                file.writeBytes(bytes)
                FileProvider.getUriForFile(ctx, ctx.packageName + ".files", file)
            }
        } catch (_: Exception) {
            null
        }
    }

    fun open(ctx: Context, uri: Uri, mime: String) {
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, mime.substringBefore(';'))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            ctx.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            // لا يوجد تطبيق يفتح هذا النوع — الملف محفوظ في التنزيلات على أي حال
        }
    }

    /** تنزيل رابط http(s) عادي عبر DownloadManager مع كوكي الجلسة. */
    fun enqueue(ctx: Context, url: String, userAgent: String, contentDisposition: String?, mime: String?) {
        val name = URLUtil.guessFileName(url, contentDisposition, mime)
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle(name)
            .setMimeType(mime)
            .addRequestHeader("User-Agent", userAgent)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        CookieManager.getInstance().getCookie(url)?.let { req.addRequestHeader("Cookie", it) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "Darb/$name")
        } else {
            req.setDestinationInExternalFilesDir(ctx, Environment.DIRECTORY_DOWNLOADS, name)
        }
        (ctx.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
    }
}
