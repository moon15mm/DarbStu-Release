package com.darbstu.app

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.webkit.WebSettings
import androidx.core.widget.doAfterTextChanged
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.darbstu.app.databinding.ActivitySchoolsBinding
import com.darbstu.app.databinding.DialogAddSchoolBinding
import com.darbstu.app.databinding.ItemSchoolBinding
import com.google.android.material.dialog.MaterialAlertDialogBuilder

/** الشاشة الأولى: قائمة المدارس المربوطة وإضافة مدرسة برمزها. */
class SchoolsActivity : AppCompatActivity() {

    private lateinit var b: ActivitySchoolsBinding
    private lateinit var store: SchoolStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivitySchoolsBinding.inflate(layoutInflater)
        setContentView(b.root)
        store = SchoolStore(this)
        b.addButton.setOnClickListener { showAddDialog(null) }

        val deepLinkCode = schoolFromIntent(intent)
        if (deepLinkCode != null) {
            showAddDialog(deepLinkCode)
        } else if (savedInstanceState == null && intent?.action == Intent.ACTION_MAIN) {
            // فتح آخر مدرسة مباشرة — زر الرجوع من داخلها يعيد إلى هذه القائمة
            store.find(store.lastHost)?.let { open(it) }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        schoolFromIntent(intent)?.let { showAddDialog(it) }
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    /** darbstu://connect?school=alnoor */
    private fun schoolFromIntent(i: Intent?): String? =
        i?.data?.takeIf { it.scheme == "darbstu" }?.getQueryParameter("school")

    private fun render() {
        val list = b.list
        // احذف كل البطاقات واترك نص «لا توجد مدارس»
        for (i in list.childCount - 1 downTo 0) {
            if (list.getChildAt(i).id != R.id.empty) list.removeViewAt(i)
        }
        val schools = store.all()
        b.empty.visibility = if (schools.isEmpty()) View.VISIBLE else View.GONE
        schools.forEach { school ->
            val item = ItemSchoolBinding.inflate(LayoutInflater.from(this), list, false)
            item.name.text = school.name
            item.host.text = school.host
            item.badge.text = school.name.trim().firstOrNull()?.toString() ?: "؟"
            item.root.setOnClickListener { open(school) }
            item.menu.setOnClickListener { v -> showMenu(v, school) }
            list.addView(item.root)
        }
    }

    private fun showMenu(anchor: View, school: School) {
        PopupMenu(this, anchor).apply {
            menu.add(0, 1, 0, R.string.rename)
            menu.add(0, 2, 1, R.string.remove)
            setOnMenuItemClickListener {
                when (it.itemId) {
                    1 -> showRenameDialog(school)
                    2 -> MaterialAlertDialogBuilder(this@SchoolsActivity)
                        .setMessage(getString(R.string.remove_confirm, school.name))
                        .setPositiveButton(R.string.remove) { _, _ -> store.remove(school.host); render() }
                        .setNegativeButton(R.string.cancel, null)
                        .show()
                }
                true
            }
            show()
        }
    }

    private fun showRenameDialog(school: School) {
        val input = EditText(this).apply { setText(school.name); setSelection(text.length) }
        val pad = (20 * resources.displayMetrics.density).toInt()
        val frame = android.widget.FrameLayout(this).apply { setPadding(pad, pad / 2, pad, 0); addView(input) }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.rename)
            .setView(frame)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val n = input.text.toString().trim()
                if (n.isNotEmpty()) { store.rename(school.host, n); render() }
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun showAddDialog(prefill: String?) {
        val d = DialogAddSchoolBinding.inflate(layoutInflater)
        prefill?.let { d.input.setText(it) }
        val dialog = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.dialog_add_title)
            .setView(d.root)
            .setPositiveButton(R.string.connect, null)   // يُربط لاحقاً حتى لا يُغلق الحوار عند الخطأ
            .setNegativeButton(R.string.cancel, null)
            .setNeutralButton(R.string.connect_anyway, null)
            .create()
        var failedHost: String? = null

        fun submit() {
            val raw = d.input.text?.toString().orEmpty()
            if (raw.isBlank()) { d.inputLayout.error = getString(R.string.err_empty); return }
            val host = SchoolStore.normalize(raw)
            if (host == null) { d.inputLayout.error = getString(R.string.err_invalid); return }
            d.inputLayout.error = null
            d.progress.visibility = View.VISIBLE
            val btn = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
            btn.isEnabled = false
            d.inputLayout.helperText = getString(R.string.checking)
            Thread {
                val result = SchoolStore.check(host, userAgent)
                runOnUiThread {
                    if (isFinishing) return@runOnUiThread
                    d.progress.visibility = View.GONE
                    d.inputLayout.helperText = null
                    btn.isEnabled = true
                    when (result) {
                        is SchoolCheck.Ok -> {
                            val name = result.schoolName.ifBlank { host.substringBefore('.') }
                            val school = School(host, name)
                            store.upsert(school)
                            Toast.makeText(this, getString(R.string.added, name), Toast.LENGTH_SHORT).show()
                            dialog.dismiss()
                            open(school)
                        }
                        SchoolCheck.NotDarb -> {
                            d.inputLayout.error = getString(R.string.err_not_darb)
                            failedHost = host
                        }
                        is SchoolCheck.Unreachable -> {
                            d.inputLayout.error = getString(R.string.err_unreachable) +
                                if (result.detail.isNotBlank()) "\n(" + host + " — " + result.detail + ")" else ""
                            failedHost = host
                        }
                    }
                    dialog.getButton(AlertDialog.BUTTON_NEUTRAL).visibility =
                        if (failedHost != null) View.VISIBLE else View.GONE
                }
            }.start()
        }

        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener { submit() }
            // «اتصال على أي حال»: يظهر بعد فشل التحقق فقط، ويفتح النطاق في
            // المتصفح الداخلي ليرى المستخدم ما يعرضه الخادم فعلاً.
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).apply {
                visibility = View.GONE
                setOnClickListener {
                    val h = failedHost ?: return@setOnClickListener
                    val school = School(h, h.substringBefore('.'))
                    store.upsert(school)
                    dialog.dismiss()
                    open(school)
                }
            }
        }
        d.input.doAfterTextChanged {
            failedHost = null
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL)?.visibility = View.GONE
        }
        d.input.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) { submit(); true } else false
        }
        dialog.show()
    }

    private val userAgent: String by lazy {
        (try { WebSettings.getDefaultUserAgent(this) } catch (_: Exception) { "Mozilla/5.0 (Linux; Android)" }) +
            " DarbStuApp/" + BuildConfig.VERSION_NAME
    }

    private fun open(school: School) {
        store.lastHost = school.host
        startActivity(Intent(this, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_HOST, school.host)
            .putExtra(MainActivity.EXTRA_NAME, school.name))
    }
}
