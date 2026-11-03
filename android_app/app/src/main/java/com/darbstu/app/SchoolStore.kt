package com.darbstu.app

import android.content.Context
import android.webkit.CookieManager
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

/** مدرسة مربوطة بالتطبيق: نطاقها العام واسمها المعروض. */
data class School(val host: String, val name: String) {
    val baseUrl: String get() = "https://$host"
    val dashboardUrl: String get() = "$baseUrl/web/dashboard"
}

/** نتيجة التحقق من نطاق مدرسة. */
sealed class SchoolCheck {
    data class Ok(val schoolName: String) : SchoolCheck()
    object NotDarb : SchoolCheck()
    object Unreachable : SchoolCheck()
}

/**
 * قائمة المدارس المحفوظة على الجهاز (SharedPreferences).
 *
 * كل مدرسة في النظام تعمل على جهازها الخاص ويصلها الإنترنت عبر نفق على
 * النطاق `<رمز>.darbstu.com`، فربط مدرسة يعني حفظ نطاقها فقط — الحسابات
 * والصلاحيات تبقى في نظام المدرسة نفسه.
 */
class SchoolStore(context: Context) {
    private val prefs = context.getSharedPreferences("schools", Context.MODE_PRIVATE)

    fun all(): List<School> {
        val arr = JSONArray(prefs.getString(KEY_LIST, "[]"))
        return (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            School(o.getString("host"), o.optString("name", o.getString("host")))
        }
    }

    private fun save(list: List<School>) {
        val arr = JSONArray()
        list.forEach { arr.put(JSONObject().put("host", it.host).put("name", it.name)) }
        prefs.edit().putString(KEY_LIST, arr.toString()).apply()
    }

    /** يضيف المدرسة أو يحدّث اسمها إن كانت موجودة، ويضعها أول القائمة. */
    fun upsert(school: School) {
        save(listOf(school) + all().filter { it.host != school.host })
    }

    fun rename(host: String, name: String) {
        save(all().map { if (it.host == host) it.copy(name = name) else it })
    }

    fun remove(host: String) {
        save(all().filter { it.host != host })
        if (lastHost == host) lastHost = null
        // تسجيل الخروج من هذه المدرسة على هذا الجهاز
        val cm = CookieManager.getInstance()
        cm.setCookie("https://$host", "darb_token=; Max-Age=0; path=/")
        cm.flush()
    }

    var lastHost: String?
        get() = prefs.getString(KEY_LAST, null)
        set(v) { prefs.edit().putString(KEY_LAST, v).apply() }

    fun find(host: String?): School? = all().firstOrNull { it.host == host }

    companion object {
        private const val KEY_LIST = "list"
        private const val KEY_LAST = "last"
        private val CODE_RE = Regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
        private val HOST_RE = Regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,}$")

        /**
         * يحوّل ما يكتبه المستخدم إلى نطاق:
         *   alnoor                          → alnoor.darbstu.com
         *   alnoor.darbstu.com              → alnoor.darbstu.com
         *   https://alnoor.darbstu.com/web  → alnoor.darbstu.com
         * يُرجع null إن كان المُدخل غير صالح.
         */
        fun normalize(input: String): String? {
            var s = input.trim().lowercase()
            if (s.isEmpty()) return null
            if (!s.contains("://")) s = "https://$s"
            val host = try { URI(s).host } catch (_: Exception) { null } ?: return null
            if (!host.contains('.')) {
                return if (CODE_RE.matches(host)) "$host.${BuildConfig.SCHOOLS_DOMAIN}" else null
            }
            return if (HOST_RE.matches(host)) host else null
        }

        /** يتحقق أن النطاق يخدم نظام درب فعلاً (عبر /health). يُستدعى خارج خيط الواجهة. */
        fun check(host: String): SchoolCheck {
            return try {
                val conn = URL("https://$host/health").openConnection() as HttpURLConnection
                conn.connectTimeout = 12000
                conn.readTimeout = 12000
                conn.setRequestProperty("Accept", "application/json")
                conn.setRequestProperty("User-Agent", "DarbStuApp")
                try {
                    if (conn.responseCode != 200) return SchoolCheck.Unreachable
                    val body = conn.inputStream.bufferedReader().use { it.readText() }
                    val json = try { JSONObject(body) } catch (_: Exception) { return SchoolCheck.NotDarb }
                    if (json.optString("status") != "ok") return SchoolCheck.NotDarb
                    SchoolCheck.Ok(json.optString("school_name", ""))
                } finally {
                    conn.disconnect()
                }
            } catch (_: Exception) {
                SchoolCheck.Unreachable
            }
        }
    }
}
