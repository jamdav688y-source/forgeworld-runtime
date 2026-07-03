package substrate.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val SubstrateColors = darkColorScheme()

@Composable
fun SubstrateTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = SubstrateColors, content = content)
}
