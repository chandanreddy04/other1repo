# Changelog

All notable changes to the Made It Home project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2025-01-18

### Added
- **Circle of Trust Feature**: Complete replacement of legacy trusted contacts system
  - Phone contact integration via Expo Contacts
  - Support for iOS partial contact access with refresh functionality
  - Automatic SMS invitations
  - Configurable contact limit (default: 3)
  - Contact search with debouncing to prevent keyboard issues

- **Modern UI Design System**: Playful Pop theme for college audience
  - Custom color palette: Teal (primary), Purple (secondary), Indigo (success), Red (danger), Yellow (warning)
  - Glassmorphism effects on cards and components
  - Consistent shadows and gradients throughout
  - Animated components (pulse animation for "I'm Safe" button)
  - Bottom sheet interface for check-in creation

### Changed
- **Navigation**: Redesigned bottom tab bar with custom icons and modern styling
- **Home Screen**: Card-based dashboard with clear status indicators
- **Contacts Screen**: Renamed to "Circle of Trust" with improved UI/UX
- **Alert System**: Unified color scheme using design system constants
- **Database Schema**: Migrated from trusted_contacts to circle_of_trust table
- **API Endpoints**: Updated to use /contacts/ with trailing slashes

### Removed
- **Legacy Contacts System**: Completely removed old trusted contacts implementation
- **Trust Levels**: Simplified model - contacts are either in Circle or not
- **Hardcoded Colors**: Replaced all inline color values with design system constants

### Fixed
- **Color Semantics**:
  - Danger color now properly red (#DC3545)
  - Warning color now properly yellow (#FFE66D)
  - Pending status uses orange (#FB923C)
- **Database Enums**: Fixed SQLAlchemy enum serialization with values_callable
- **API Integration**: Corrected endpoint URLs and field mappings
- **Search Functionality**: Fixed keyboard closing issue with proper debouncing
- **Contact Refresh**: Implemented proper permission re-request for iOS/Android

### Technical Details

#### Frontend Changes
- Updated all components to use COLORS constants from design system
- Implemented Zustand store for Circle of Trust state management
- Added ContactsPermissionModal for permission flow
- Created ContactSelector component with search functionality
- Redesigned CircleOfTrustCard without trust level indicators

#### Backend Changes
- Created new migration: 002_circle_of_trust.py
- Updated trusted_contact model with new fields
- Added Circle of Trust settings endpoints
- Fixed enum handling in SQLAlchemy models

#### Database Schema Updates
```sql
-- New fields added to trusted_contacts table
ALTER TABLE trusted_contacts ADD COLUMN contact_name VARCHAR(100);
ALTER TABLE trusted_contacts ADD COLUMN contact_phone_number VARCHAR(20);
ALTER TABLE trusted_contacts ADD COLUMN contact_email VARCHAR(255);
ALTER TABLE trusted_contacts ADD COLUMN is_app_user BOOLEAN DEFAULT FALSE;
ALTER TABLE trusted_contacts ADD COLUMN app_user_id UUID;
ALTER TABLE trusted_contacts ADD COLUMN is_mutual BOOLEAN DEFAULT FALSE;
ALTER TABLE trusted_contacts ADD COLUMN priority_level VARCHAR(20);
```

### Dependencies
- expo-contacts: ^13.0.5 (added for phone contact integration)

### Breaking Changes
- **API Endpoint Restructure**: All `/contacts/` endpoints moved to `/circle-of-trust/` with RESTful patterns
  - Old: `/api/v1/contacts/` → New: `/api/v1/circle-of-trust/`
  - Old: `/api/v1/contacts/circle-of-trust/settings` → New: `/api/v1/circle-of-trust/settings`
  - Old: `/api/v1/contacts/accept/{code}` → New: `/api/v1/circle-of-trust/{code}/accept`
  - Old: `/api/v1/contacts/send-sms-invite/{id}` → New: `/api/v1/circle-of-trust/{id}/invite`
- Removed trust_level field, replaced with simplified model
- Changed field names: contact_phone_number -> contact_phone in some contexts

### Migration Guide
For existing installations:
1. Run database migration: `alembic upgrade head`
2. Update API calls to use new endpoints with trailing slashes
3. Clear app data or reinstall to reset contact permissions
4. Re-import contacts through new Circle of Trust interface

## [1.0.0] - 2025-01-10

### Initial Release
- User authentication with JWT tokens
- Basic check-in system with timers
- Push notifications via Expo
- Outfit photo capture
- Alert system for missed check-ins
- Profile management
- Cross-platform support (iOS/Android)
