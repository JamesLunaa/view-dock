plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "dev.viewdock.android"
    compileSdk = 37

    defaultConfig {
        applicationId = "dev.viewdock.android"
        minSdk = 26
        targetSdk = 35
        // versionName tracks the repo release (see CHANGELOG.md). versionCode must only
        // ever increase for an update to install over an older build; major*10000 +
        // minor*100 + patch keeps it in step with versionName (2.0.0 -> 20000).
        versionCode = 20000
        versionName = "2.0.0"
    }

    buildTypes {
        release {
            // Unsigned until a release keystore is configured; the debug
            // build is what gets sideloaded during development.
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        // libwebrtc ships its native libs per ABI; keep them uncompressed-
        // friendly and avoid duplicate-license merge failures.
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/DEPENDENCIES")
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.androidx.activity.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.stream.webrtc)
    implementation(libs.java.websocket)

    testImplementation(libs.junit)
    testImplementation(libs.org.json)
}
