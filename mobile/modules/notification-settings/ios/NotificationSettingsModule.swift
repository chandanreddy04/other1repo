import ExpoModulesCore
import UIKit

// Opens the app's own notification settings directly, using Apple's public
// URL constant (iOS 15.4+). There's no public JS/Expo API for this, so this
// tiny native module bridges it. Falls back to the general app-settings page
// on older iOS. Android is handled in JS via expo-intent-launcher.
public class NotificationSettingsModule: Module {
  public func definition() -> ModuleDefinition {
    Name("NotificationSettings")

    AsyncFunction("openNotificationSettings") { (promise: Promise) in
      DispatchQueue.main.async {
        let urlString: String
        if #available(iOS 16.0, *) {
          urlString = UIApplication.openNotificationSettingsURLString
        } else if #available(iOS 15.4, *) {
          urlString = UIApplicationOpenNotificationSettingsURLString
        } else {
          urlString = UIApplication.openSettingsURLString
        }
        guard let url = URL(string: urlString) else {
          promise.resolve(false)
          return
        }
        UIApplication.shared.open(url, options: [:]) { success in
          promise.resolve(success)
        }
      }
    }
  }
}
