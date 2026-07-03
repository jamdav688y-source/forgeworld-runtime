package substrate.app.ui.landscape

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import substrate.app.data.dao.EdgeDao
import substrate.app.data.dao.NodeDao
import substrate.app.ui.SimpleViewModelFactory
import substrate.core.model.NodeType
import substrate.core.model.RenderedNode
import substrate.core.model.RuntimeSnapshot

private val DOMAIN_COLORS: Map<NodeType, Color> = mapOf(
    NodeType.OBSERVATION to Color(0xFF64B5F6),
    NodeType.MEMORY to Color(0xFFBA68C8),
    NodeType.RESEARCH to Color(0xFF4DD0E1),
    NodeType.PROJECTS to Color(0xFFFFB74D),
    NodeType.RUNTIME to Color(0xFF90A4AE),
    NodeType.GOVERNANCE to Color(0xFFE57373),
    NodeType.COMMERCIAL to Color(0xFF81C784),
    NodeType.MEDIA to Color(0xFFF06292),
    NodeType.LEARNING to Color(0xFFFFD54F),
    NodeType.SYNCHRONIZATION to Color(0xFF9575CD),
)

/**
 * The "neural landscape" — every value drawn here comes from [RuntimeSnapshot],
 * which is built exclusively from Room-backed repository state (see
 * [NeuralLandscapeViewModel]). Layout is a deterministic radial placement (one
 * angular sector per [NodeType], radius driven by importance) rather than a
 * force-directed simulation — documented as a known simplification, not a
 * physics engine.
 */
@Composable
fun NeuralLandscapeScreen(nodeDao: NodeDao, edgeDao: EdgeDao, modifier: Modifier = Modifier) {
    val viewModel: NeuralLandscapeViewModel = viewModel(factory = SimpleViewModelFactory { NeuralLandscapeViewModel(nodeDao, edgeDao) })
    val snapshot by viewModel.snapshot.collectAsState()

    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    // Pulse Frequency = Runtime Activity: period shortens as more nodes have
    // fired in the last minute (activityPulseFrequencyHz), never a fixed constant.
    val periodMillis = (1200 / (snapshot.activityPulseFrequencyHz + 0.05)).toInt().coerceIn(300, 4000)
    val pulse by infiniteTransition.animateFloat(
        initialValue = 0.85f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(tween(periodMillis, easing = LinearEasing), RepeatMode.Reverse),
        label = "pulseScale",
    )

    Canvas(modifier = modifier.fillMaxSize()) {
        val center = Offset(size.width / 2f, size.height / 2f)
        val maxRadius = min(size.width, size.height) / 2.4f
        val positions = layoutRadial(snapshot, center, maxRadius)

        snapshot.edges.forEach { edge ->
            val from = positions[edge.fromNodeId] ?: return@forEach
            val to = positions[edge.toNodeId] ?: return@forEach
            val recency = ((snapshot.generatedAtMillis - edge.lastReinforcedAtMillis).coerceAtLeast(0)).toFloat()
            val alpha = (1f - (recency / 300_000f)).coerceIn(0.08f, 0.9f) // fades over 5 minutes
            drawLine(
                color = Color.White.copy(alpha = alpha),
                start = from,
                end = to,
                strokeWidth = (1f + edge.weight.toFloat() * 1.5f).coerceAtMost(10f),
            )
        }

        snapshot.nodes.forEach { rendered ->
            val pos = positions[rendered.node.id] ?: return@forEach
            val domainColor = DOMAIN_COLORS[rendered.node.type] ?: Color.Gray
            val brightness = (0.35 + rendered.currentActivation.coerceIn(0.0, 1.0) * 0.65).toFloat()
            val radius = (6f + rendered.node.importance.toFloat() * 3f).coerceAtMost(40f) * pulse
            drawCircle(
                color = domainColor.copy(alpha = brightness),
                radius = radius,
                center = pos,
            )
            drawCircle(
                color = domainColor,
                radius = radius,
                center = pos,
                style = Stroke(width = 1.5f),
            )
        }
    }
}

/**
 * One angular sector per [NodeType] (36 degrees each, 10 domains); within a
 * sector, radius from center is inversely proportional to importance (highly
 * reinforced concepts pull toward the core) with a per-node hash offset so
 * nodes in the same domain/importance band don't collide exactly.
 */
private fun layoutRadial(snapshot: RuntimeSnapshot, center: Offset, maxRadius: Float): Map<String, Offset> {
    val maxImportance = snapshot.nodes.maxOfOrNull { it.node.importance }?.coerceAtLeast(0.1) ?: 1.0
    val bucketed = snapshot.nodes.groupBy { it.node.type }

    val positions = mutableMapOf<String, Offset>()
    bucketed.forEach { (type, nodesInDomain) ->
        val sectorStart = type.ordinal * (2 * PI / NodeType.entries.size)
        val sectorWidth = 2 * PI / NodeType.entries.size
        nodesInDomain.forEachIndexed { index, rendered: RenderedNode ->
            val jitter = if (nodesInDomain.size > 1) (index.toDouble() / nodesInDomain.size) * sectorWidth * 0.8 else sectorWidth / 2
            val angle = sectorStart + jitter
            val normalizedImportance = (rendered.node.importance / maxImportance).coerceIn(0.0, 1.0)
            val radius = maxRadius * (0.25f + (1f - normalizedImportance.toFloat()) * 0.7f)
            positions[rendered.node.id] = Offset(
                x = center.x + (radius * cos(angle)).toFloat(),
                y = center.y + (radius * sin(angle)).toFloat(),
            )
        }
    }
    return positions
}
