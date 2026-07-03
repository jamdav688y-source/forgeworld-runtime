package substrate.core.pipeline

import kotlin.math.pow
import substrate.core.model.GraphNode

/**
 * Stage 4: Generate Activation Pulse. Node brightness in the neural landscape
 * is exponential-decay activation, not a fixed value — nodes genuinely dim
 * over time and brighten again on reactivation.
 */
object ActivationPulseGenerator {
    /** Activation halves every 6 hours of inactivity. */
    const val DECAY_HALF_LIFE_MILLIS = 6L * 60 * 60 * 1000
    const val PULSE_BOOST = 1.0

    fun decayedActivation(node: GraphNode, nowMillis: Long): Double {
        if (node.lastActivatedAtMillis <= 0L || node.activation <= 0.0) return 0.0
        val elapsed = (nowMillis - node.lastActivatedAtMillis).coerceAtLeast(0L)
        val halfLives = elapsed.toDouble() / DECAY_HALF_LIFE_MILLIS
        return node.activation * 0.5.pow(halfLives)
    }

    /** Applies decay to `node`'s current activation, then adds a fresh pulse. */
    fun pulse(node: GraphNode, nowMillis: Long): GraphNode {
        val decayed = decayedActivation(node, nowMillis)
        return node.copy(activation = decayed + PULSE_BOOST, lastActivatedAtMillis = nowMillis)
    }
}
