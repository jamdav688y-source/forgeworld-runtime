package substrate.app.ui.audit

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import substrate.app.data.dao.AuditDao
import substrate.app.ui.SimpleViewModelFactory

@Composable
fun AuditTrailScreen(auditDao: AuditDao, modifier: Modifier = Modifier) {
    val viewModel: AuditTrailViewModel = viewModel(factory = SimpleViewModelFactory { AuditTrailViewModel(auditDao) })
    val entries by viewModel.recentEntries.collectAsState()

    LazyColumn(modifier = modifier.fillMaxSize().padding(12.dp)) {
        items(entries) { entry ->
            Text("[${entry.stage}]  ${entry.summary}")
            Text("eventId=${entry.eventId}  t=${entry.timestampMillis}", style = MaterialTheme.typography.labelSmall)
            Divider()
        }
    }
}
