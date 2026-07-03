package substrate.app.ui.landscape

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.delay
import substrate.app.data.dao.EdgeDao
import substrate.app.data.dao.NodeDao
import substrate.app.data.repository.toModel
import substrate.core.model.RenderedNode
import substrate.core.model.RuntimeSnapshot
import substrate.core.pipeline.ActivationPulseGenerator

/**
 * Reactive counterpart to [substrate.core.pipeline.RuntimeSnapshotBuilder]:
 * same decay math (re-used directly from `core`, not re-implemented), but
 * driven by a Room `Flow` + a 500ms clock tick so the landscape visibly dims
 * between events, satisfying Runtime Invariants #7/#8 continuously rather
 * than only at submission time.
 */
class NeuralLandscapeViewModel(
    nodeDao: NodeDao,
    edgeDao: EdgeDao,
) : ViewModel() {

    private val clockTick = flow {
        while (true) {
            emit(System.currentTimeMillis())
            delay(500)
        }
    }

    val snapshot: StateFlow<RuntimeSnapshot> = combine(nodeDao.observeAll(), edgeDao.observeAll(), clockTick) { nodeEntities, edgeEntities, now ->
        val nodes = nodeEntities.map { entity ->
            val node = entity.toModel()
            RenderedNode(node = node, currentActivation = ActivationPulseGenerator.decayedActivation(node, now))
        }
        val edges = edgeEntities.map { it.toModel() }
        val recentlyActive = nodes.count { it.node.lastActivatedAtMillis > 0 && now - it.node.lastActivatedAtMillis <= 60_000 }
        RuntimeSnapshot(
            generatedAtMillis = now,
            nodes = nodes,
            edges = edges,
            activityPulseFrequencyHz = (recentlyActive.toDouble() / 60.0).coerceAtLeast(0.0),
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = RuntimeSnapshot(System.currentTimeMillis(), emptyList(), emptyList(), 0.0),
    )
}
