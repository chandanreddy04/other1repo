import { registerRootComponent } from 'expo'
import { Platform } from 'react-native'
import './services/locationTracking' // Register background location task

// Register Android foreground service for ongoing session notification
if (Platform.OS === 'android') {
  import('@notifee/react-native')
    .then(({ default: notifee }) => {
      notifee.registerForegroundService(() => {
        return new Promise(() => {
          // Keep service running until explicitly stopped
        })
      })
    })
    .catch(() => {
      // Notifee not available (e.g., Expo Go)
    })
}

import App from './App'

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App)
