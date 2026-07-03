package substrate.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import substrate.app.ui.audit.AuditTrailScreen
import substrate.app.ui.capture.CaptureScreen
import substrate.app.ui.landscape.NeuralLandscapeScreen
import substrate.app.ui.theme.SubstrateTheme

/**
 * "The user never launches isolated applications." In practice that means one
 * Activity with three observation surfaces on the same underlying substrate —
 * Capture (introduce an event), Landscape (watch what activated), Audit
 * (inspect why) — not three unrelated feature screens.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as SubstrateApplication

        setContent {
            SubstrateTheme {
                SubstrateApp(app)
            }
        }
    }
}

private sealed class Destination(val route: String, val label: String) {
    data object Capture : Destination("capture", "Capture")
    data object Landscape : Destination("landscape", "Landscape")
    data object Audit : Destination("audit", "Audit")
}

@Composable
private fun SubstrateApp(app: SubstrateApplication) {
    val navController = rememberNavController()
    val destinations = listOf(Destination.Capture, Destination.Landscape, Destination.Audit)

    Scaffold(
        bottomBar = {
            NavigationBar {
                val backStackEntry by navController.currentBackStackEntryAsState()
                val currentDestination = backStackEntry?.destination
                destinations.forEach { destination ->
                    NavigationBarItem(
                        selected = currentDestination?.hierarchy?.any { it.route == destination.route } == true,
                        onClick = {
                            navController.navigate(destination.route) {
                                popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Text(destination.label.take(1)) },
                        label = { Text(destination.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(navController = navController, startDestination = Destination.Capture.route, modifier = Modifier.padding(padding)) {
            composable(Destination.Capture.route) { CaptureScreen(pipeline = app.eventPipeline) }
            composable(Destination.Landscape.route) { NeuralLandscapeScreen(nodeDao = app.database.nodeDao(), edgeDao = app.database.edgeDao()) }
            composable(Destination.Audit.route) { AuditTrailScreen(auditDao = app.database.auditDao()) }
        }
    }
}
