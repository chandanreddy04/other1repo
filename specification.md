# Made It Home - Product Specification v1.0

## Executive Summary

Made It Home is a personal safety application designed for college students that enables automated check-ins and emergency notifications. Users can set expected return times before going out, and trusted contacts are alerted if the user fails to check in by the specified deadline.

## Product Overview

### Vision
Create a simple, reliable safety net for college students that provides peace of mind without being intrusive or complicated to use.

### Target Audience
- Primary: College students (ages 18-24)
- Secondary: Young professionals, solo travelers (future expansion)

### Core Value Proposition
- Automated safety check-ins without constant location tracking
- Quick setup for spontaneous outings
- Non-intrusive design that respects user privacy
- Reliable notification system for trusted contacts

## User Stories

### Primary User Stories

1. **As a college student**, I want to quickly set a check-in time before going out, so my friends/family know to check on me if I don't return.

2. **As a college student**, I want to easily check in when I'm home safe, so my trusted contacts don't worry.

3. **As a college student**, I want to add trusted contacts who will be notified if I don't check in, so someone knows if something might be wrong.

4. **As a trusted contact**, I want to receive clear notifications when someone hasn't checked in, so I can take appropriate action.

5. **As a user**, I want to extend my check-in time if plans change, so I don't trigger false alarms.

## Feature Specifications

### 1. User Registration & Profile

#### Requirements:
- Phone number-based OTP authentication (no email/password required)
- SMS verification with 6-digit codes
- Basic profile information (name, phone number)
- Optional profile photo
- Emergency contact information

#### Technical Considerations:
- Phone numbers stored in E164 format
- OTP codes expire after 10 minutes
- Rate limiting on OTP requests (1 per minute)
- phonenumbers library for validation and formatting

### 2. Circle of Trust Management

#### Requirements:
- Add up to 3 trusted contacts (configurable limit)
- Direct phone contact import via Expo Contacts
- Automatic SMS invitations
- Simple add/remove interface
- No trust levels - all contacts are equal
- iOS partial contact access support with refresh

#### User Flow:
1. User grants contact permissions (full or partial on iOS)
2. Select contacts from phone's contact list
3. Contacts are added to Circle of Trust
4. Optional SMS invitations sent automatically

### 3. Creating a Safety Check-In

#### Requirements:
- Quick-start button on home screen
- Set expected return time (default options: 2hr, 4hr, 6hr, custom)
- **Outfit photo capture** (helps with identification if needed)
  - Optional but encouraged
  - Auto-delete after check-in completed + 24 hours
  - Shared with trusted contacts only if alert triggered
- Optional: Add destination/activity description
- Optional: Share live location during outing
- Confirmation screen with summary including outfit photo

#### Quick Setup Options:
- "Going out for the evening" (4-6 hours)
- "Quick errand" (30-60 minutes)
- "Night out" (6-8 hours)
- "Custom time"

### 4. Check-In System

#### Requirements:
- Large, prominent "Made It Home" button
- Multiple check-in methods:
  - In-app button
  - SMS reply
  - Voice command integration (Siri/Google Assistant)
- Reminder notifications at:
  - 30 minutes before deadline
  - 15 minutes before deadline
  - At deadline

#### Safety Features:
- PIN/biometric verification for check-in (optional)
- Duress code that appears to check in but actually alerts contacts

### 5. Alert System

#### Alert Triggers:
- User misses check-in deadline
- User activates panic button
- User enters duress code

#### Alert Escalation:
1. **T+0 minutes**: Push notification to user
2. **T+5 minutes**: SMS to user
3. **T+10 minutes**: Notify primary trusted contacts
4. **T+30 minutes**: Notify all trusted contacts
5. **T+60 minutes**: Share last known location (if enabled)

#### Alert Information Includes:
- User's name and photo
- Expected return time
- Time elapsed since deadline
- **Outfit photo from check-in start**
- Last known location (if shared)
- Destination/activity (if provided)
- Quick action buttons (Call, Text, View Map)

### 6. Privacy & Safety Features

#### Requirements:
- Location sharing is always optional
- All data encrypted in transit and at rest
- Auto-delete old check-in data after 30 days
- Private mode (hide activity from certain contacts)
- Block/report functionality

### 7. Additional Features

#### Quick Actions:
- "Extend time" button (30min, 1hr, 2hr increments)
- "SOS" emergency button (prominent red button)
- Quick share current location
- "I'm Safe" button for active alerts

#### Statistics & History:
- Check-in history (last 30 days)
- Safety score/streak
- Most frequent check-in times

## User Interface Design Guidelines

### Design Principles:
- **Simplicity First**: Core actions achievable in 2-3 taps
- **High Contrast**: Easy to use in low light/impaired conditions
- **Large Touch Targets**: Accommodate stress situations
- **Clear Visual Hierarchy**: Most important actions prominent

### Key Screens:

1. **Home Screen**
   - Large "Start Safety Check-In" button
   - Active check-in status card (if applicable)
   - Quick access to trusted contacts
   - Menu for settings/history

2. **Check-In Setup**
   - Time selector (visual picker)
   - Camera interface for outfit photo
   - Optional fields collapsed by default
   - Clear "Start" confirmation with photo preview

3. **Active Check-In**
   - Countdown timer display
   - Large "Made It Home" button
   - "Extend Time" option
   - Emergency button (requires hold or double-tap)

4. **Trusted Contact View**
   - List of contacts with status
   - Add contact button
   - Pending invitations section

## Technical Architecture

### Platform Requirements:
- **Cross-platform mobile app using Expo SDK**
  - iOS 14+, Android 8+ support from launch
  - Expo SDK 53 with React Native 0.79.5
  - Managed workflow for simplified development
  - Expo modules for platform-specific features
- Web dashboard for trusted contacts (React)
- Backend API service
- Push notification service via Expo
- SMS gateway integration

### Expo Implementation Details:

#### Core Dependencies:
- **Expo SDK 53** - Complete development platform
- **React Native** 0.79.5 (via Expo)
- **Expo Router** v4 - File-based navigation and deep linking
- **Expo Contacts** - Phone contacts integration for Circle of Trust
- **Expo Image Picker** - Camera interface for outfit photos
- **Expo Secure Store** - Secure local storage for sensitive data
- **Expo Notifications** - Local and remote push notifications
- **Expo Local Authentication** - Face ID/Touch ID/Fingerprint auth

#### Key Libraries for Features:
- **Camera/Photos**:
  - `expo-image-picker` - Camera interface and photo selection
  - `expo-image` - Optimized image loading and caching
  - `expo-image-manipulator` - Compress outfit photos before upload
- **Notifications**:
  - `expo-notifications` - Complete notification solution
  - Expo Push Service - No Firebase configuration needed
- **Background Tasks**:
  - `expo-background-fetch` - Background processing
  - `expo-task-manager` - Task scheduling
  - React hooks for countdown timers
- **Security**:
  - `expo-secure-store` - Secure credential storage
  - `expo-local-authentication` - Biometric authentication
  - `expo-crypto` - Cryptographic operations
- **UI Components**:
  - `expo-haptics` - Haptic feedback
  - `react-native-reanimated` - Performance animations
  - `react-native-safe-area-context` - Handle device safe areas
  - `nativewind` - Tailwind CSS for React Native

#### State Management:
- **Zustand** - Lightweight state management
- Async storage via `@react-native-async-storage/async-storage`

#### Development Tools:
- **Expo Dev Tools** - Built-in debugging
- **React Native Debugger** - Component inspection
- **Sentry** - Crash reporting via `sentry-expo`
- **EAS Update** - Over-the-air updates (replaces CodePush)

### Native Functionality via Expo:
Expo handles most native functionality automatically:
- **Push notifications** - Expo Push Service (no Firebase setup required)
- **Camera permissions** - Handled by Expo Image Picker
- **Background location** (if enabled) - Expo Location module
- **SMS integration** - Expo Linking for deep links
- **Voice assistant integration** (Phase 2) - Requires Expo development build

### Recommended Tech Stack:
- **Frontend**: Expo SDK with React Native
- **Web Dashboard**: React (potential code sharing with Expo web)
- **State Management**: Zustand (lightweight and TypeScript-friendly)
- **Backend**: Python/FastAPI
- **Database**: PostgreSQL with Redis for caching
- **Background Jobs**: Celery with Redis/RabbitMQ
- **Media Storage**: AWS S3 for outfit photos
- **Push Notifications**: Expo Push Service
- **SMS**: Twilio
- **Analytics**: Expo Analytics or Amplitude

### Backend Architecture (FastAPI):

#### API Structure:
```
/api/v1/
├── auth/          # Registration, login, JWT tokens
├── users/         # User profile management
├── contacts/      # Trusted contacts CRUD
├── checkins/      # Create, update, complete check-ins
├── alerts/        # Alert management and history
├── notifications/ # Push notification triggers
└── webhooks/      # Twilio SMS webhooks
```

#### Key Python Dependencies:
- **FastAPI** - High-performance async API framework
- **SQLAlchemy** 2.0+ - ORM with async support
- **Alembic** - Database migrations
- **Pydantic** - Data validation and settings
- **python-jose** - JWT token handling
- **celery** - Background task processing
- **redis-py** - Redis client for caching
- **boto3** - AWS S3 for photo storage
- **twilio** - SMS integration
- **exponent-server-sdk** - Expo push notifications

#### Background Tasks (Celery):
- Check-in deadline monitoring
- Alert escalation logic
- Notification scheduling
- Photo cleanup (24hr deletion)
- Analytics event processing

### Do We Need Real-time?

**Short answer: No, real-time isn't necessary for MVP.**

The app can work effectively with:
1. **Push notifications** for immediate alerts
2. **Polling** (every 30-60 seconds) when check-in screen is active
3. **Background fetch** for timer updates

**Why real-time isn't critical:**
- Users aren't constantly watching the app
- Push notifications handle urgent communications
- Check-in status changes are infrequent
- Polling is sufficient for countdown timer updates

**Future consideration:**
Add WebSockets in Phase 3 if you want:
- Live location sharing
- Instant status updates on web dashboard
- Group check-in features
- Real-time panic button alerts

For now, FastAPI's standard REST endpoints + push notifications will provide a responsive experience while keeping the architecture simpler.

### Data Model:

```
Users
- user_id (UUID)
- phone_number (primary identifier, E164 format)
- full_name (optional, can be set after registration)
- name
- profile_photo_url
- created_at
- settings (JSON)

CircleOfTrust
- id (UUID)
- user_id (FK)
- contact_name
- contact_phone_number
- is_app_user
- app_user_id (FK, optional)
- status (active/pending/blocked)
- created_at
- updated_at

CheckIns
- checkin_id (UUID)
- user_id (FK)
- expected_return_time
- actual_return_time
- destination (optional)
- outfit_photo_url (optional)
- location_sharing_enabled
- status (active/completed/missed)
- created_at

Alerts
- alert_id (UUID)
- checkin_id (FK)
- alert_type
- sent_to_user_id
- sent_at
- acknowledged_at
```

### Development & Deployment Considerations:

#### Expo Specific:
- **Bundle Size**: Expo handles optimization automatically
- **Performance**: 60 FPS for all interactions
- **Offline Support**: Core check-in functionality works offline
- **Error Boundaries**: Graceful error handling to prevent crashes
- **Platform Differences**:
  - iOS: Expo handles App Store requirements
  - Android: Expo ensures compatibility across devices
- **EAS Build**: Cloud-based build service for production apps
- **EAS Submit**: Automated store submission

#### Code Sharing Strategy:
- Shared components between Expo and React web dashboard:
  - API client and data models
  - Business logic and validation
  - Date/time utilities
  - Notification formatting
  - Zustand stores (with platform adapters)
- Platform-specific:
  - UI components (Expo components for mobile)
  - Navigation patterns (Expo Router vs React Router)
  - Device-specific features (handled by Expo SDK)

### Security Considerations:
- End-to-end encryption for sensitive data
- Rate limiting on all API endpoints
- Audit logging for all safety-critical actions
- Regular security penetration testing
- GDPR/CCPA compliance

## Success Metrics

### User Engagement:
- Daily Active Users (DAU)
- Average check-ins per user per week
- Check-in completion rate
- Time to complete check-in

### Safety Metrics:
- False alarm rate
- Response time to alerts
- Successful safety interventions

### Growth Metrics:
- User acquisition rate
- Trusted contact acceptance rate
- User retention (30-day, 90-day)
- Network effects (users per trusted contact network)

## Launch Strategy

### MVP Features (Phase 1 - Completed):
1. User registration with JWT authentication
2. Circle of Trust with phone contact integration (up to 3)
3. Simple check-in creation with outfit photo
4. In-app check-in with countdown timer
5. Alert system with automatic Circle notifications
6. **Cross-platform Expo app (iOS & Android)**
7. Biometric authentication support
8. Secure credential storage
9. Modern Playful Pop design system with glassmorphism

### Phase 2 Additions:
- SMS check-in
- Advanced location sharing features
- Extended trusted contacts
- Check-in history with photo gallery
- Voice assistant integration (native development)

### Phase 3 Expansion:
- Web dashboard
- Real-time features (WebSockets)
- Voice assistant integration
- Duress codes
- Group events
- Campus/organization partnerships

## Implementation Timeline

### Development Phases with React Native:

#### Phase 0: Setup (Completed)
- Expo environment setup
- EAS Build configuration
- Expo project initialization
- Expo Router navigation structure
- Zustand state management setup

#### Phase 1: Core Features (Week 3-8)
- Authentication flow
- Camera integration for outfit photos
- Check-in timer system
- Push notification setup
- Basic trusted contacts

#### Phase 2: Safety Features (Week 9-12)
- Alert system implementation
- SMS integration with Twilio
- Background timer handling
- "Made It Home" check-in flow
- Emergency features

#### Phase 3: Polish & Testing (Week 13-16)
- UI/UX refinement
- Performance optimization
- Beta testing with college students
- App store preparation
- Security audit

### Expo Best Practices:
1. **Use TypeScript** for better code quality and developer experience
2. **Implement proper deep linking** with Expo Router
3. **Test with Expo Go** during development, EAS Build for production
4. **Set up EAS Update** for over-the-air updates
5. **Expo handles bundle optimization** automatically
6. **Hermes is enabled by default** in Expo SDK 48+

## Potential Challenges & Mitigations

### Challenge: Alert Fatigue
**Mitigation**: Smart notification timing, customizable alert preferences, ML-based anomaly detection

### Challenge: Privacy Concerns
**Mitigation**: Clear data policies, optional features, regular privacy audits, transparent communication

### Challenge: Battery Drain
**Mitigation**: Efficient background processing, optional location features, battery optimization guidelines

### Challenge: False Alarms
**Mitigation**: Grace periods, easy extension options, reminder notifications, user education

## Future Considerations

- Integration with campus safety systems
- Wearable device support
- AI-powered risk assessment
- Community safety features
- International expansion with local emergency service integration

## Conclusion

Made It Home aims to provide a simple, effective safety tool that college students will actually use. By focusing on ease of use, respecting privacy, and building trust with reliable functionality, the app can become an essential part of students' safety routines without feeling burdensome or invasive.
