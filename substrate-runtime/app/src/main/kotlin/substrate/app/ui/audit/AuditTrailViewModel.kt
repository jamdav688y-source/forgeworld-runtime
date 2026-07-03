package substrate.app.ui.audit

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import substrate.app.data.dao.AuditDao
import substrate.app.data.entity.AuditEntity

/**
 * Observability requirement: every decision must be inspectable. This screen
 * has no separate "audit data model" — it renders [AuditEntity] rows exactly
 * as [substrate.core.orchestrator.EventPipeline] wrote them, most recent first.
 */
class AuditTrailViewModel(auditDao: AuditDao) : ViewModel() {
    val recentEntries: StateFlow<List<AuditEntity>> = auditDao.observeRecent()
        .map { it }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
}
