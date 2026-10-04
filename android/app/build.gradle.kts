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
        versionCode = 1
        versionName = "0.1.0"
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
