Pod::Spec.new do |s|
  s.name           = 'NotificationSettings'
  s.version        = '1.0.0'
  s.summary        = 'Deep-link to the app notification settings (iOS)'
  s.description    = 'Local Expo module bridging UIApplicationOpenNotificationSettingsURLString.'
  s.license        = 'MIT'
  s.author         = 'Made It Home'
  s.homepage       = 'https://www.madeithomeapp.com'
  s.platforms      = { :ios => '15.1' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
  }

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
